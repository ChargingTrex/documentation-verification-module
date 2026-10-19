"""
Hard-fact extraction from resume text: years of experience and education level.

Regex-based, as the PRD specifies. Ported from the resume-matcher prototype,
with three corrections that mattered on real resumes:

1. The prototype's `b\\.?e\\.?` pattern ran case-insensitively, so the ordinary
   English word "be" marked every resume as holding a bachelor's degree.
   Bare abbreviations are now matched case-sensitively (BE, BTech, MCA...),
   while spelled-out forms stay case-insensitive.
2. `m\\.?s\\.?` matched "MS Office", "MS SQL" and "MS Teams" -- a skills list
   was enough to claim a master's. Those product names are now excluded.
3. Experience was the maximum number before the word "years" anywhere in the
   document, so "4 years full-time degree" outranked "2 years experience".
   Durations stated near the word "experience" now win; the old
   whole-document maximum is only the fallback.

Later corrections, each pinned by a test in `tests/test_extractors.py`:

4. A stated age ("Age: 22 years", "21 years old") was read as experience, so
   a fresher looked senior. Ages are now excluded, and read by `find_age`.
5. Study durations ("10 years of schooling", "4 years B.Tech programme") no
   longer reach the fallback pool.
6. Date ranges ("Jun 2023 - Present") were invisible; they are now summed,
   overlaps merged, but only inside an experience section or on a line that
   names a role.
7. `m\\.?\\s?e\\.\\b` could never match "M.E." before a space, because there is
   no word boundary between "." and " ". The dotted forms now end in
   `\\.(?!\\w)` and require the inner dot, so "contact me." stays prose.

8. An age cue swallowed real claims ("Age: 22, Experience: 2 years"). A
   duration with an experience word between the cue and itself, or nearer
   than the cue, is a claim; "I am" cues an age only directly before the
   number ("I am 21 years").
9. Every pattern's whitespace is bounded and the proximity checks look only
   at a small window around each duration, because the upload pre-fill runs
   synchronously: crafted text took minutes and could stall a worker.

`find_age`, `find_date_of_birth`, `find_emails`, `find_phones` and
`find_cgpa` exist for preliminary verification only. None of them feeds
ranking or eligibility; the roster stays authoritative.
"""

from __future__ import annotations

import bisect
import datetime
import re
from dataclasses import dataclass

# Ordered weakest to strongest; the portal reports the highest level found.
EDUCATION_ORDER: tuple[str, ...] = ("UG", "Masters", "PG")

# Holding a higher degree implies the ones beneath it, whether or not the
# resume spells them out. Without this, a filter for "UG" would reject a
# master's graduate who only listed their most recent qualification.
IMPLIED_BY = {
    "PG": {"Masters", "UG"},
    "Masters": {"UG"},
    "UG": set(),
}

# A resume claiming more than this is a parsing accident, not a candidate.
MAX_PLAUSIBLE_YEARS = 50.0

#: The extractors read at most this much text. A long four-page resume is
#: about 15,000 characters; anything past this is padding or an attack, and
#: reading it would only cost the synchronous upload time.
MAX_EXTRACT_CHARS = 60_000

#: How far either side of a duration the proximity checks look. Three words
#: rarely take more than 40 characters, so this loses no real claim while
#: keeping the work per duration constant rather than per document.
CONTEXT_CHARS = 80

_HORIZONTAL_SPACE = re.compile(r"[^\S\n]+")


def _bounded(text: str | None) -> str:
    """The text the extractors read: capped, with runs of spaces collapsed."""
    return _HORIZONTAL_SPACE.sub(" ", (text or "")[:MAX_EXTRACT_CHARS])

# A duration counts as an experience claim when it sits right next to the
# word "experience" -- at most this many words apart, with no sentence break
# between them. "2 years of professional experience" qualifies; "4 year
# full-time degree. 2 years experience" attributes the 2, not the 4.
EXPERIENCE_GAP_WORDS = 3
_SENTENCE_BREAK = re.compile(r"[.;:!?\n]")

_EXPERIENCE_WORD = re.compile(r"\b(?:experience|experienced|exp\.?)\b", re.IGNORECASE)
# "Experience: 2 years" is a label, not a sentence break.
_LABEL_GAP = re.compile(r"^\s{0,3}[:\-\u2013]\s{0,3}")

# An age is not experience. A cue within this many words before the
# duration, or "old" / "of age" straight after it, marks it as an age.
AGE_CUE_WORDS = 3
_AGE_BREAK = re.compile(r"[.;!?\n]")  # a colon is part of "Age: 22"
_AGE_CUE = re.compile(
    r"\b(?:age|aged|(?P<i_am>i\s{1,3}am|i'm)|dob|d\.o\.b|date\s{1,3}of\s{1,3}birth)\b", re.IGNORECASE
)
_AGE_SUFFIX = re.compile(r"[\s-]{0,3}(?:old\b|of\s{1,3}age\b)", re.IGNORECASE)

# How long a course of study took is not experience either: the plan's cue
# words, plus the degree names the education patterns already know, so
# "2 years MBA" and "4 year B.E." leave the fallback pool too.
_STUDY_CUE = re.compile(
    r"\b(?:schooling|programme|program|course|degree|semesters?|curriculum|diploma|"
    r"(?:under|post)?[\s-]?graduation|of\s(?:engineering|college|university)|"
    r"b\.?\s?tech|m\.?\s?tech|b\.?\s?sc|m\.?\s?sc|b\.?\s?com|bca|bba|mca|mba|ph\.?\s?d|"
    r"b\.\s?e\.|m\.\s?e\.|bachelor'?s?|master'?s?)(?!\w)",
    re.IGNORECASE,
)

# "one year", "a year": spelled numbers, only directly before a unit.
_WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12,
}
_WORD_NUMBER = re.compile(
    r"\b(" + "|".join(_WORD_NUMBERS) + r")(?=\s{1,3}(?:years?|yrs?|months?|mos?)\b)",
    re.IGNORECASE,
)

# "3 years", "3+ yrs", "2-4 years", optionally followed by "and 6 months".
# Every gap is bounded: three adjacent unbounded `\s*` made a digit followed
# by 20,000 spaces take twenty seconds.
_YEARS = re.compile(
    r"(?<![\d.])(?P<low>\d{1,2}(?:\.\d{1,2})?)\s{0,3}"
    r"(?:\+|(?:-|–|to)\s{0,3}(?P<high>\d{1,2}(?:\.\d{1,2})?))?\s{0,3}"
    r"(?:years?|yrs?\.?)"
    r"(?:\s{0,3}(?:,|and)?\s{0,3}(?P<months>\d{1,2})\s{0,3}(?:months?|mos?\.?))?",
    re.IGNORECASE,
)
_MONTHS = re.compile(r"(?<![\d.])(?P<months>\d{1,2})\s{0,3}\+?\s{0,3}(?:months?|mos?\.?)", re.IGNORECASE)

# --- Education patterns ------------------------------------------------------
# Spelled-out forms are safe case-insensitively.
_UG_WORDS = [
    r"bachelor(?:'?s)?(?:\s+of\s+\w+)?",
    r"under[\s-]?graduate",
    r"b\.?\s?tech\b",
    # Both dots required, so "be" and "be." in prose cannot match.
    r"b\.\s?e\.(?!\w)",
]
# "diploma", but not "PG diploma" / "post graduate diploma". Handled per line,
# because an online course calling itself a diploma is not a UG degree.
_DIPLOMA = re.compile(
    r"(?<!pg\s)(?<!post\sgraduate\s)(?<!postgraduate\s)diploma", re.IGNORECASE
)
_NOT_A_DIPLOMA = re.compile(
    r"course|certificat|udemy|coursera|nptel|online|edx", re.IGNORECASE
)
_MASTERS_WORDS = [
    # Whole words only, and not the Scrum role: "Masterclass" and "Certified
    # Scrum Master" are not degrees.
    r"(?<!scrum\s)\bmaster(?:'?s)?\b(?:\s+of\s+\w+)?",
    r"post[\s-]?graduat(?:e|ion)",
    r"pg\s+diploma",
    r"m\.?\s?tech\b",
    r"m\.\s?e\.(?!\w)",
]
_PG_WORDS = [r"ph\.?\s?d\b", r"doctorate", r"doctoral"]

# Bare abbreviations: uppercase only, because lowercase versions collide with
# ordinary words and product names.
_UG_ABBREVIATIONS = [r"\bB\.?E\.?\b", r"\bB\.?Tech\b", r"\bB\.?Sc\b", r"\bBCA\b", r"\bBBA\b", r"\bB\.?Com\b"]
_MASTERS_ABBREVIATIONS = [
    r"\bM\.?Tech\b",
    # "M.E (Civil)": the inner dot is required, so the word "ME" stays prose.
    r"\bM\.E\b",
    r"\bM\.?Sc\b",
    r"\bMCA\b",
    r"\bMBA\b",
    # "MS" only when it is not the Microsoft prefix.
    r"\bM\.S\.?\b",
    r"\bMS\b(?!\s{0,3}(?:Office|Word|Excel|SQL|Teams|Azure|Project|Visio|Access|Outlook|Power|Dynamics|Windows|Server))",
]
_PG_ABBREVIATIONS = [r"\bPh\.?D\b"]

_SPELLED = {
    "UG": [re.compile(pattern, re.IGNORECASE) for pattern in _UG_WORDS],
    "Masters": [re.compile(pattern, re.IGNORECASE) for pattern in _MASTERS_WORDS],
    "PG": [re.compile(pattern, re.IGNORECASE) for pattern in _PG_WORDS],
}
_ABBREVIATED = {
    "UG": [re.compile(pattern) for pattern in _UG_ABBREVIATIONS],
    "Masters": [re.compile(pattern) for pattern in _MASTERS_ABBREVIATIONS],
    "PG": [re.compile(pattern) for pattern in _PG_ABBREVIATIONS],
}


@dataclass(frozen=True)
class Duration:
    """One duration found in the text, and whether it was an experience claim."""

    years: float
    near_experience: bool
    snippet: str
    #: The length of a course of study, not of a job.
    is_study: bool = False


def _to_years(match: re.Match) -> float:
    """A match's duration in years, taking the upper bound of any range."""
    low = float(match.group("low"))
    high = match.groupdict().get("high")
    years = float(high) if high else low
    months = match.groupdict().get("months")
    if months:
        years += float(months) / 12.0
    return years


def _experience_gap(text: str, start: int, end: int) -> int | None:
    """
    Words between this duration and the nearest experience word that makes
    it a claim, or None when it is not a claim *about* experience.

    Only a window of CONTEXT_CHARS either side is searched, so a document of
    repeated claims costs linear time, not one scan per duration.
    """
    lo, hi = max(0, start - CONTEXT_CHARS), min(len(text), end + CONTEXT_CHARS)
    best: int | None = None
    # A little past `hi`, so a word cut at the window edge ("exp|erience")
    # is never mistaken for the abbreviation "exp".
    for word in _EXPERIENCE_WORD.finditer(text, lo, min(len(text), hi + 20)):
        if word.start() >= hi:
            break
        if word.start() >= end:
            gap = text[end : word.start()]
        elif word.end() <= start:
            gap = _LABEL_GAP.sub(" ", text[word.end() : start], count=1)
        else:
            continue
        if gap and _SENTENCE_BREAK.search(gap):
            continue  # a different sentence: not this duration's claim
        words = len(gap.split())
        if words <= EXPERIENCE_GAP_WORDS and (best is None or words < best):
            best = words
    return best


def _is_near_experience(text: str, start: int, end: int) -> bool:
    """True when this duration reads as a claim *about* experience."""
    return _experience_gap(text, start, end) is not None


def _alnum_words(text: str) -> int:
    return sum(1 for token in text.split() if any(ch.isalnum() for ch in token))


def _is_age(text: str, start: int, end: int, claim_gap: int | None = None) -> bool:
    """
    True when this duration is somebody's age ("Age: 22 years", "21 years old").

    A claim beats the cue: "Age: 22, Experience: 2 years" is two years of
    experience, because "Experience" sits between the cue and the duration.
    So does an experience word nearer the duration than the cue. "I am" is
    a weak cue -- "I am having 2 years of experience" is a claim -- so it
    counts only directly before the number.
    """
    if _AGE_SUFFIX.match(text, end):
        return True
    lo = max(0, start - CONTEXT_CHARS)
    before = _AGE_BREAK.split(text[lo:start])[-1]
    words = before.split()
    cut = lo > 0 and len(before) == start - lo and not text[lo - 1].isspace() and not text[lo].isspace()
    if cut and words:
        words = words[1:]  # the window cut a word in half: "home|page" is not "age"
    window = " ".join(words[-(AGE_CUE_WORDS + 1) :])

    cues = list(_AGE_CUE.finditer(window))
    if not cues:
        return False
    cue = cues[-1]
    between = window[cue.end() :]
    if _EXPERIENCE_WORD.search(between):
        return False
    distance = _alnum_words(between)
    if cue.group("i_am"):
        return distance == 0 and claim_gap is None
    return claim_gap is None or claim_gap > distance


def _is_study(text: str, start: int, end: int) -> bool:
    """True when this duration is the length of a course ("4 years B.Tech")."""
    lo, hi = max(0, start - CONTEXT_CHARS), min(len(text), end + CONTEXT_CHARS)
    for cue in _STUDY_CUE.finditer(text, lo, min(len(text), hi + 20)):
        if cue.start() >= hi:
            break
        if cue.start() >= end:
            gap = text[end : cue.start()]
        elif cue.end() <= start:
            gap = text[cue.end() : start]
        else:
            continue
        if _SENTENCE_BREAK.search(gap):
            continue
        if len(gap.split()) <= EXPERIENCE_GAP_WORDS:
            return True
    return False


def _normalise_numbers(text: str) -> str:
    """'one year' -> '1 year', so the duration patterns can read it."""
    return _WORD_NUMBER.sub(lambda m: str(_WORD_NUMBERS[m.group(1).lower()]), text)


def find_durations(text: str) -> list[Duration]:
    """
    Every duration in the text that could be work experience, with its
    proximity to the word 'experience'. Ages are left out entirely.
    """
    text = _bounded(text)
    if not text:
        return []

    text = _normalise_numbers(text)
    durations: list[Duration] = []
    consumed_starts: list[int] = []
    consumed_ends: list[int] = []

    def add(match: re.Match, years: float) -> None:
        start, end = match.span()
        claim_gap = _experience_gap(text, start, end)
        if _is_age(text, start, end, claim_gap):
            return
        durations.append(
            Duration(
                years=years,
                near_experience=claim_gap is not None,
                snippet=match.group(0).strip(),
                is_study=_is_study(text, start, end),
            )
        )

    for match in _YEARS.finditer(text):
        consumed_starts.append(match.start())
        consumed_ends.append(match.end())
        add(match, _to_years(match))

    for match in _MONTHS.finditer(text):
        # Skip a months figure already absorbed by a "X years Y months" match.
        # The year matches do not overlap, so they are sorted by start.
        i = bisect.bisect_right(consumed_starts, match.start()) - 1
        if i >= 0 and match.start() < consumed_ends[i]:
            continue
        add(match, float(match.group("months")) / 12.0)

    return [d for d in durations if 0 < d.years <= MAX_PLAUSIBLE_YEARS]


# --- date ranges -------------------------------------------------------------

_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)


def _date_pattern(p: str) -> str:
    """
    One side of a range: "Jun 2023", "Jan'23", "06/2023", "5/24" or a bare
    "2023". A two-digit year is read as 20yy; it needs the apostrophe or the
    slash, so a stray "Jun 23" (a day) is not taken for a year.
    """
    year = r"(?:19|20)\d{2}"
    return (
        rf"(?:(?P<{p}mon>{_MONTH})[\s,']{{0,3}}(?P<{p}my>{year})"
        rf"|(?P<{p}mon2>{_MONTH})\s?['\u2019]\s?(?P<{p}yy2>\d{{2}})"
        rf"|(?P<{p}mm>0?[1-9]|1[0-2])\s{{0,2}}[/\-.]\s{{0,2}}(?P<{p}ny>{year})"
        rf"|(?P<{p}mm2>0?[1-9]|1[0-2])/(?P<{p}yy>\d{{2}})"
        rf"|(?P<{p}y>{year}))"
    )


_OPEN_END = r"(?P<now>present|current(?:ly)?|now|ongoing|till\s{1,3}date|to\s{1,3}date|date)"
_DATE_RANGE = re.compile(
    r"(?<![\d/])"
    + _date_pattern("s")
    + r"\s{0,3}(?:-|\u2013|\u2014|to|until|till)\s{0,3}"
    + rf"(?:{_OPEN_END}|{_date_pattern('e')})"
    + r"(?![\d/])",
    re.IGNORECASE,
)

_EXPERIENCE_HEADERS = {
    "experience", "work experience", "professional experience", "relevant experience",
    "internships", "internship", "internship experience", "internships & experience",
    "employment", "employment history", "work history", "experience & internships",
}
_OTHER_HEADERS = {
    "education", "academics", "academic details", "academic qualifications",
    "qualifications", "educational qualifications", "projects", "academic projects",
    "personal projects", "skills", "technical skills", "key skills", "certifications",
    "certificates", "courses", "achievements", "awards", "awards & achievements",
    "extracurricular", "extra-curricular activities", "activities", "summary",
    "profile", "objective", "career objective", "publications", "interests",
    "hobbies", "languages", "positions of responsibility", "volunteering",
    "personal details", "declaration", "references",
}
_ROLE_CUE = re.compile(
    r"\b(?:intern(?:ship)?|engineer|developer|analyst|associate|consultant|executive|"
    r"manager|designer|trainee|assistant|scientist|programmer|specialist|officer|"
    r"coordinator|freelance(?:r)?|architect|administrator|technician|tester)\b",
    re.IGNORECASE,
)
_EDUCATION_CUE = re.compile(
    r"\b(?:b\.?\s?tech|m\.?\s?tech|b\.?e\.|bachelor|master|degree|school|college|"
    r"university|institute|cgpa|gpa|cpi|hsc|ssc|class\s+(?:x|xii|10|12)|pursuing|"
    r"semester|bca|bba|mca|mba|b\.?sc|m\.?sc|ph\.?d|diploma)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DateRange:
    """One period of work read off the resume, both end months included."""

    start: tuple[int, int]
    end: tuple[int, int]
    snippet: str

    @property
    def months(self) -> int:
        return (self.end[0] - self.start[0]) * 12 + (self.end[1] - self.start[1]) + 1


def _parse_point(match: re.Match, prefix: str) -> tuple[int, int | None] | None:
    """(year, month) for one side of a range; month is None for a bare year."""
    group = match.groupdict()
    if group.get(f"{prefix}mon"):
        return int(group[f"{prefix}my"]), _MONTH_NAMES[group[f"{prefix}mon"][:3].lower()]
    if group.get(f"{prefix}mon2"):
        return 2000 + int(group[f"{prefix}yy2"]), _MONTH_NAMES[group[f"{prefix}mon2"][:3].lower()]
    if group.get(f"{prefix}mm"):
        return int(group[f"{prefix}ny"]), int(group[f"{prefix}mm"])
    if group.get(f"{prefix}mm2"):
        return 2000 + int(group[f"{prefix}yy"]), int(group[f"{prefix}mm2"])
    if group.get(f"{prefix}y"):
        return int(group[f"{prefix}y"]), None
    return None


_HEADER_TRAIL = re.compile(r"[\s:|\-_=*#]+$")
_HEADER_EXPERIENCE_WORD = re.compile(r"\b(?:experiences?|internships?)\b", re.IGNORECASE)
_HEADER_CONNECTORS = {"and", "&", "/", "of", "in", "-", "|"}


def _looks_like_a_header(line: str) -> bool:
    """Short, no digits, every word capitalised: "WORK EXPERIENCE AND INTERNSHIPS"."""
    words = line.split()
    if not words or len(words) > 5 or any(ch.isdigit() for ch in line):
        return False
    return all(w.lower() in _HEADER_CONNECTORS or w[0].isupper() for w in words)


def _header(line: str) -> str | None:
    """'experience', 'education' or 'other' when this line is a section header."""
    stripped = _HEADER_TRAIL.sub("", line.strip())
    cleaned = stripped.lower()
    if not cleaned or len(cleaned.split()) > 5:
        return None
    if cleaned in _EXPERIENCE_HEADERS:
        return "experience"
    if cleaned in _OTHER_HEADERS:
        return "education" if cleaned.startswith(("education", "academic", "qualif")) else "other"
    # A header the lists do not name ("Internship Details") still opens an
    # experience section; otherwise the internship under it would be read
    # as part of the education section above.
    if _HEADER_EXPERIENCE_WORD.search(cleaned) and _looks_like_a_header(stripped):
        return "experience"
    return None


def _experience_lines(text: str) -> list[tuple[str, bool]]:
    """
    The lines whose date ranges count as work, each with whether it sits
    inside an explicit experience section.

    With an experience header, only that section counts. Without one, a line
    counts when it names a role, carries no education cue, and is not under
    an education header -- so a B.Tech's "Aug 2022 - May 2026" is never read
    as four years of work.
    """
    lines = text.split("\n")
    headers = [_header(line) for line in lines]
    has_experience_section = "experience" in headers

    picked: list[tuple[str, bool]] = []
    section: str | None = None
    for line, header in zip(lines, headers):
        if header:
            section = header
            continue
        if has_experience_section:
            if section == "experience":
                picked.append((line, True))
        elif section != "education" and _ROLE_CUE.search(line) and not _EDUCATION_CUE.search(line):
            picked.append((line, False))
    return picked


def find_date_ranges(text: str, today: datetime.date | None = None) -> list[DateRange]:
    """
    Work periods stated as date ranges ("Jun 2023 - Present", "06/2024 - 08/2024").

    A range that starts with a bare year ("2019 - 2021", "2024 - Present")
    counts only inside an experience section. A year-only range counts as
    whole years (2019 - 2021 is two): without months a range cannot say
    whether it covered one year or nearly three.
    """
    text = _bounded(text)
    if not text:
        return []
    today = today or datetime.date.today()
    now = (today.year, today.month)

    ranges: list[DateRange] = []
    for line, in_section in _experience_lines(text):
        for match in _DATE_RANGE.finditer(line):
            start = _parse_point(match, "s")
            end = now if match.group("now") else _parse_point(match, "e")
            if start is None or end is None:
                continue

            if start[1] is None and not in_section:
                continue
            if start[1] is None and end[1] is None:
                if end[0] <= start[0]:
                    continue
                first, last = (start[0], 1), (end[0] - 1, 12)
            else:
                first, last = (start[0], start[1] or 1), (end[0], end[1] or 12)

            last = min(last, now)
            if last < first:
                continue
            ranges.append(DateRange(first, last, match.group(0).strip()))
    return ranges


def merged_months(spans: list[tuple[tuple[int, int], tuple[int, int]]]) -> int:
    """
    Total months across (start, end) month spans, both ends included,
    counting an overlap once. Shared with the LLM path in `matching/llm.py`.
    """
    if not spans:
        return 0
    ordered = sorted((s[0] * 12 + s[1], e[0] * 12 + e[1]) for s, e in spans)
    total, (cur_start, cur_end) = 0, ordered[0]
    for start, end in ordered[1:]:
        if start <= cur_end + 1:
            cur_end = max(cur_end, end)
        else:
            total += cur_end - cur_start + 1
            cur_start, cur_end = start, end
    return total + cur_end - cur_start + 1


@dataclass(frozen=True)
class ExperienceReading:
    """Years of experience, and which rule produced the figure."""

    years: float
    #: "claim" (stated near "experience"), "date_ranges", "fallback", or "none".
    source: str


def find_experience(text: str, today: datetime.date | None = None) -> ExperienceReading:
    """
    Total years of experience in the text, to one decimal place.

    Precedence: a duration stated as experience, then the merged total of
    the date ranges, then the largest remaining duration that is neither an
    age nor the length of a course.
    """
    durations = find_durations(text)

    claims = [d for d in durations if d.near_experience]
    if claims:
        return ExperienceReading(round(max(d.years for d in claims), 1), "claim")

    months = merged_months([(r.start, r.end) for r in find_date_ranges(text, today)])
    if months:
        return ExperienceReading(round(min(months / 12.0, MAX_PLAUSIBLE_YEARS), 1), "date_ranges")

    fallback = [d for d in durations if not d.is_study]
    if fallback:
        return ExperienceReading(round(max(d.years for d in fallback), 1), "fallback")

    return ExperienceReading(0.0, "none")


def find_experience_years(text: str) -> float:
    """Total years of experience in the text. See `find_experience`."""
    return find_experience(text).years


def find_education_levels(text: str) -> set[str]:
    """Education levels literally named in the text ({'UG', 'Masters', 'PG'})."""
    text = _bounded(text)
    if not text:
        return set()

    found: set[str] = set()
    for level in EDUCATION_ORDER:
        spelled = any(pattern.search(text) for pattern in _SPELLED[level])
        abbreviated = any(pattern.search(text) for pattern in _ABBREVIATED[level])
        if spelled or abbreviated:
            found.add(level)

    if any(
        _DIPLOMA.search(line) and not _NOT_A_DIPLOMA.search(line)
        for line in text.split("\n")
    ):
        found.add("UG")
    return found


def effective_education_levels(levels: set[str]) -> set[str]:
    """The named levels plus the ones they imply (a master's implies a UG)."""
    effective = set(levels)
    for level in levels:
        effective |= IMPLIED_BY[level]
    return effective


def highest_education_level(levels: set[str]) -> str | None:
    """The strongest level present, or None when nothing was detected."""
    for level in reversed(EDUCATION_ORDER):
        if level in levels:
            return level
    return None


# --- verification-only facts -------------------------------------------------
# Read so an admin can compare the resume with the roster and the form. None
# of these is ranked on, filtered on, or shown to a company.

AGE_RANGE = (14, 70)

_STATED_AGE = [
    re.compile(r"\bage[d]?\s{0,3}[:\-–]?\s{0,3}(?P<age>\d{2})\b", re.IGNORECASE),
    re.compile(r"\b(?P<age>\d{2})[\s-]{0,3}(?:years?|yrs?)[\s-]{0,3}old\b", re.IGNORECASE),
    re.compile(r"\b(?P<age>\d{2})\s{0,3}(?:years?|yrs?)\s{1,3}of\s{1,3}age\b", re.IGNORECASE),
]


def find_age(text: str) -> int | None:
    """The age the resume states, or None. Admin verification only."""
    text = _bounded(text)
    if not text:
        return None
    for pattern in _STATED_AGE:
        for match in pattern.finditer(text):
            age = int(match.group("age"))
            if AGE_RANGE[0] <= age <= AGE_RANGE[1]:
                return age
    return None


_DOB_CUE = r"(?:d\.?\s?o\.?\s?b\.?|date\s{1,3}of\s{1,3}birth|born(?:\s{1,3}on)?)\s{0,3}[:\-–]?\s{0,3}"
_DOB_PATTERNS = [
    # 12/03/2003, 12-03-2003, 12.03.2003 -- day first, as Indian resumes write it
    re.compile(_DOB_CUE + r"(?P<d>\d{1,2})[/\-.](?P<m>\d{1,2})[/\-.](?P<y>(?:19|20)\d{2})\b", re.IGNORECASE),
    # 2003-03-12
    re.compile(_DOB_CUE + r"(?P<y>(?:19|20)\d{2})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b", re.IGNORECASE),
    # 12 March 2003, 12th Mar 2003
    re.compile(
        _DOB_CUE + r"(?P<d>\d{1,2})(?:st|nd|rd|th)?\s{1,3}(?P<mon>" + _MONTH + r")[\s,]{1,3}(?P<y>(?:19|20)\d{2})\b",
        re.IGNORECASE,
    ),
    # March 12, 2003
    re.compile(
        _DOB_CUE + r"(?P<mon>" + _MONTH + r")\s{1,3}(?P<d>\d{1,2})(?:st|nd|rd|th)?,?\s{1,3}(?P<y>(?:19|20)\d{2})\b",
        re.IGNORECASE,
    ),
]


def find_date_of_birth(text: str) -> datetime.date | None:
    """The date of birth the resume states, or None. Admin verification only."""
    text = _bounded(text)
    if not text:
        return None
    for pattern in _DOB_PATTERNS:
        for match in pattern.finditer(text):
            group = match.groupdict()
            month = (
                _MONTH_NAMES[group["mon"][:3].lower()] if group.get("mon") else int(group["m"])
            )
            try:
                return datetime.date(int(group["y"]), month, int(group["d"]))
            except ValueError:
                continue  # 31/02/2003: not a date
    return None


# Starts only at the beginning of a run, and both parts are bounded (RFC
# 5321's 64 and 253): unbounded, 40 KB of "aaa@bbb" took seconds.
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,24}(?![A-Za-z])"
)


def find_emails(text: str) -> list[str]:
    """Email addresses in the order they appear, lowercased, once each."""
    seen: dict[str, None] = {}
    for match in _EMAIL.finditer(_bounded(text)):
        seen.setdefault(match.group(0).lower().rstrip("."), None)
    return list(seen)


# An Indian mobile: optional +91 / 91 / 0, then ten digits starting 6-9,
# grouped 5-5, 3-3-4 or 4-3-3.
_PHONE = re.compile(
    r"(?<![\d+])(?:\+?91[\s\-]?|0)?"
    r"(?P<number>[6-9]\d{4}[\s\-]?\d{5}"
    r"|[6-9]\d{2}[\s\-]?\d{3}[\s\-]?\d{4}"
    r"|[6-9]\d{3}[\s\-]?\d{3}[\s\-]?\d{3})(?![\d\-])"
)


def find_phones(text: str) -> list[str]:
    """Mobile numbers normalised to ten digits, in order, once each."""
    seen: dict[str, None] = {}
    for match in _PHONE.finditer(_bounded(text)):
        seen.setdefault(re.sub(r"\D", "", match.group("number")), None)
    return list(seen)


# A semester GPA ("SGPA 9.2 (Sem 5)") is not the cumulative figure, so it is
# not a cue. A bare "GPA" is, but see `find_cgpa` on four-point scales.
_CGPA_WORD = r"(?:(?P<cgpa>c\.?g\.?p\.?a|cpi)|(?P<gpa>cumulative\s{1,3}gpa|gpa))"
_CGPA_AFTER = re.compile(
    rf"\b{_CGPA_WORD}\b\s{{0,3}}(?:of|is|:|-|–|=)?\s{{0,3}}(?P<value>\d{{1,2}}(?:\.\d{{1,2}})?)"
    r"(?:\s{0,3}/\s{0,3}(?P<scale>\d{1,2}(?:\.0+)?))?",
    re.IGNORECASE,
)
_CGPA_BEFORE = re.compile(
    rf"(?<![\d.])(?P<value>\d{{1,2}}(?:\.\d{{1,2}})?)(?:\s{{0,3}}/\s{{0,3}}(?P<scale>\d{{1,2}}(?:\.0+)?))?"
    rf"\s{{0,3}}{_CGPA_WORD}\b",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"(?P<value>\d{2}(?:\.\d{1,2})?)\s{0,3}%")
_DEGREE_LINE = re.compile(
    r"\b(?:b\.?\s?tech|b\.e\.|bachelor|degree|graduat|aggregate|b\.?sc|bca|bba|b\.?com|"
    r"m\.?\s?tech|master|mca|mba|m\.?sc|diploma)",
    re.IGNORECASE,
)
# "BE: 78.4 %": uppercase only, as in the education patterns, so "be" stays prose.
_DEGREE_ABBREVIATION = re.compile(r"\b[BM]\.?E\b")
_SCHOOL_LINE = re.compile(r"\b(?:class|std|standard|grade|hsc|ssc|cbse|icse|x|xii|10th|12th)\b", re.IGNORECASE)

#: CBSE's published conversion, used only when a resume gives a degree
#: percentage and no CGPA.
PERCENT_PER_CGPA_POINT = 9.5


def find_cgpa(text: str) -> float | None:
    """
    The ten-point CGPA the resume claims, or None.

    Verification only: the roster CGPA stays authoritative for eligibility,
    and this is never stored as a profile value (see DECISIONS.md, R5).
    A four-point GPA is not converted -- there is no honest conversion --
    and a bare "GPA" of 4 or less with no scale may well be one, so it is
    not read either.
    """
    text = _bounded(text)
    if not text:
        return None

    for pattern in (_CGPA_AFTER, _CGPA_BEFORE):
        for match in pattern.finditer(text):
            scale = match.group("scale")
            if scale and float(scale) != 10.0:
                continue
            value = float(match.group("value"))
            if match.group("gpa") and not scale and value <= 4:
                continue
            if 0 < value <= 10:
                return round(value, 2)

    for line in text.split("\n"):
        if not (_DEGREE_LINE.search(line) or _DEGREE_ABBREVIATION.search(line)) or _SCHOOL_LINE.search(line):
            continue
        match = _PERCENT.search(line)
        if match and 35 <= float(match.group("value")) <= 100:
            return round(min(float(match.group("value")) / PERCENT_PER_CGPA_POINT, 10.0), 2)
    return None
