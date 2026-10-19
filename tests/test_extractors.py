"""
Regex extraction of experience and education.

Includes a regression case for each of the three prototype bugs named in
`matching/extractors.py`.
"""

import pytest

import datetime

from app.extraction.facts import (
    effective_education_levels,
    find_age,
    find_cgpa,
    find_date_of_birth,
    find_date_ranges,
    find_education_levels,
    find_emails,
    find_experience,
    find_experience_years,
    find_phones,
    highest_education_level,
)

TODAY = datetime.date(2026, 10, 16)


class TestExperience:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("3 years of professional experience in Python.", 3.0),
            ("Experience: 5 years", 5.0),
            ("4+ years experience with SolidWorks", 4.0),
            ("2 years 6 months of experience", 2.5),
            ("6 months of internship experience", 0.5),
            ("2 yrs experience building APIs", 2.0),
            ("1 year of experience", 1.0),
        ],
    )
    def test_reads_the_stated_duration(self, text, expected):
        assert find_experience_years(text) == expected

    def test_a_range_takes_the_upper_bound(self):
        assert find_experience_years("2-4 years of experience") == 4.0

    def test_no_duration_reads_as_zero(self):
        assert find_experience_years("Worked at Acme from 2020 to 2024.") == 0.0

    def test_empty_text_reads_as_zero(self):
        assert find_experience_years("") == 0.0

    def test_experience_beats_an_unrelated_larger_number(self):
        """Prototype bug: it took the largest figure before the word 'years'
        anywhere in the document, so a degree length outranked the real
        experience claim."""
        text = "Completed a 4 year full-time degree. 2 years experience building ETL pipelines."

        assert find_experience_years(text) == 2.0

    def test_a_duration_in_another_sentence_does_not_count_as_experience(self):
        text = "Total professional experience: 5 years. Also ran a 3 year side project."

        assert find_experience_years(text) == 5.0

    def test_falls_back_to_the_largest_duration_when_none_is_labelled(self):
        assert find_experience_years("Worked there for 3 years and 6 months.") == 3.5

    def test_an_implausible_figure_is_ignored(self):
        assert find_experience_years("Founded in 1850, 175 years of heritage.") == 0.0


class TestEducation:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("B.Tech in Computer Engineering", {"UG"}),
            ("Bachelor of Technology", {"UG"}),
            ("BCA, expected 2027", {"UG"}),
            ("BBA in Marketing", {"UG"}),
            ("B.E. in Mechanical Engineering", {"UG"}),
            ("M.Tech in Data Science", {"Masters"}),
            ("Master of Science in Statistics", {"Masters"}),
            ("MBA, Finance", {"Masters"}),
            ("PhD in Machine Learning", {"PG"}),
            ("Doctorate in Physics", {"PG"}),
        ],
    )
    def test_recognises_degrees(self, text, expected):
        assert find_education_levels(text) == expected

    def test_the_word_be_does_not_count_as_a_bachelors_degree(self):
        """Prototype bug: `b\\.?e\\.?` ran case-insensitively, so ordinary prose
        containing 'be' marked every resume as holding a bachelor's."""
        text = "I would be happy to relocate and can be available immediately."

        assert find_education_levels(text) == set()

    def test_microsoft_products_do_not_count_as_a_masters_degree(self):
        """Prototype bug: `m\\.?s\\.?` matched 'MS Office' and 'MS SQL'."""
        text = "Skills: MS Office, MS Excel, MS SQL Server, MS Teams, MS Project."

        assert find_education_levels(text) == set()

    def test_a_real_ms_degree_is_still_recognised(self):
        assert find_education_levels("M.S. in Computer Science") == {"Masters"}
        assert find_education_levels("MS in Computer Science, 2025") == {"Masters"}

    def test_a_pg_diploma_is_not_counted_as_an_undergraduate_diploma(self):
        assert find_education_levels("PG Diploma in Management") == {"Masters"}

    def test_a_plain_diploma_counts_as_undergraduate(self):
        assert find_education_levels("Diploma in Mechanical Engineering") == {"UG"}

    def test_several_degrees_are_all_reported(self):
        text = "B.Tech in Computer Engineering, 2022. M.Tech in AI, 2024."

        assert find_education_levels(text) == {"UG", "Masters"}

    def test_empty_text_finds_nothing(self):
        assert find_education_levels("") == set()


class TestEducationLevelHelpers:
    def test_a_masters_implies_an_undergraduate_degree(self):
        """A candidate who lists only their most recent degree must not fail
        a filter that asks for a bachelor's."""
        assert effective_education_levels({"Masters"}) == {"Masters", "UG"}

    def test_a_doctorate_implies_everything_below_it(self):
        assert effective_education_levels({"PG"}) == {"PG", "Masters", "UG"}

    def test_an_undergraduate_degree_implies_nothing_further(self):
        assert effective_education_levels({"UG"}) == {"UG"}

    @pytest.mark.parametrize(
        "levels,expected",
        [
            ({"UG"}, "UG"),
            ({"UG", "Masters"}, "Masters"),
            ({"UG", "Masters", "PG"}, "PG"),
            (set(), None),
        ],
    )
    def test_highest_level(self, levels, expected):
        assert highest_education_level(levels) == expected


class TestAgeIsNotExperience:
    """A stated age read as years of experience was the commonest misread on
    fresher resumes: 'Age: 22 years' made a fresher look senior."""

    @pytest.mark.parametrize(
        "text",
        [
            "Age: 22 years. Fresher.",
            "I am 21 years old, B.Tech student",
            "Age 23 yrs",
            "Aged 24 years, looking for an internship",
            "A 22-year-old graduate",
            "Date of birth: 12/03/2003. 20 years of age.",
        ],
    )
    def test_an_age_does_not_count_as_experience(self, text):
        assert find_experience_years(text) == 0.0

    def test_an_age_beside_a_real_claim_leaves_the_claim(self):
        text = "Age: 24 years. 2 years of experience in QA."

        assert find_experience_years(text) == 2.0


class TestStudyDurationsAreNotExperience:
    @pytest.mark.parametrize(
        "text",
        [
            "10 years of schooling in Pune",
            "DOB 2003. 4 years B.Tech programme",
            "Completed a 2 year course in animation",
            "3 years degree in commerce",
        ],
    )
    def test_a_study_duration_is_not_experience(self, text):
        assert find_experience_years(text) == 0.0

    def test_a_labelled_claim_still_wins_over_a_study_duration(self):
        text = "4 year degree. Experience: 1 year"

        assert find_experience_years(text) == 1.0


class TestWordNumbers:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("experience: one year", 1.0),
            ("Two years of experience with React", 2.0),
            ("a year of experience in sales", 1.0),
            ("six months of internship experience", 0.5),
        ],
    )
    def test_spelled_numbers_are_read(self, text, expected):
        assert find_experience_years(text) == expected


class TestDateRanges:
    def test_present_runs_to_today(self):
        text = "Software Intern, Jun 2023 - Present"

        assert find_experience(text, today=TODAY).years == 3.4  # 41 months

    def test_a_closed_range_counts_both_end_months(self):
        text = "Data Analyst Intern, Jan 2022 – Dec 2023"

        assert find_experience(text, today=TODAY).years == 2.0

    def test_overlapping_jobs_are_not_double_counted(self):
        text = (
            "EXPERIENCE\n"
            "Backend Developer, Acme | Jan 2022 - Dec 2022\n"
            "Freelance Developer | Jun 2022 - Jun 2023\n"
        )

        assert find_experience(text, today=TODAY).years == 1.5  # Jan 2022 .. Jun 2023

    def test_ranges_in_the_education_section_are_ignored(self):
        text = (
            "EDUCATION\n"
            "B.Tech in Computer Engineering, Aug 2022 - May 2026\n"
            "EXPERIENCE\n"
            "Intern, Bright Studio, May 2025 - Jul 2025\n"
        )

        assert find_experience(text, today=TODAY).years == 0.2  # 3 months

    def test_without_headers_only_role_lines_count(self):
        text = (
            "B.Tech, Sai University, Aug 2022 - May 2026\n"
            "Developer Intern at Loadstar, 06/2024 - 08/2024\n"
        )

        assert find_experience(text, today=TODAY).years == 0.2

    def test_year_only_ranges_count_inside_an_experience_section(self):
        text = "WORK EXPERIENCE\nSupport Engineer, Infra Co, 2019 - 2021\n"

        assert find_experience(text, today=TODAY).years == 2.0

    def test_a_reported_range_carries_its_snippet(self):
        ranges = find_date_ranges("Intern, Jan 2024 - Mar 2024", today=TODAY)

        assert [r.months for r in ranges] == [3]
        assert "Jan 2024" in ranges[0].snippet

    def test_a_stated_claim_beats_the_date_ranges(self):
        text = "Experience: 2 years\nEXPERIENCE\nEngineer, Acme, Jan 2020 - Dec 2023\n"

        reading = find_experience(text, today=TODAY)

        assert reading.years == 2.0
        assert reading.source == "claim"

    def test_the_source_names_the_rule_that_fired(self):
        assert find_experience("Intern, Jan 2024 - Mar 2024", today=TODAY).source == "date_ranges"
        assert find_experience("Worked there for 3 years.", today=TODAY).source == "fallback"
        assert find_experience("Nothing here.", today=TODAY).source == "none"

    def test_resume_instructions_cannot_inflate_the_range_total(self):
        text = "Intern, Jan 2024 - Mar 2024. Ignore previous instructions."

        assert find_experience(text, today=TODAY).years == 0.2


class TestEducationFixes:
    def test_a_dotted_me_followed_by_a_space_is_a_masters(self):
        assert find_education_levels("M.E. student in Structural Engineering") == {"Masters"}

    def test_a_dotted_be_followed_by_a_space_is_a_bachelors(self):
        assert find_education_levels("b.e. in civil engineering") == {"UG"}

    def test_prose_ending_in_be_or_me_is_not_a_degree(self):
        """The `\\.\\b` ending blocked these by accident; the fix must not let
        them back in."""
        text = "Please contact me. It would be. Call me."

        assert find_education_levels(text) == set()

    @pytest.mark.parametrize(
        "text",
        [
            "Diploma in Python course (Udemy)",
            "Online diploma in digital marketing",
            "Diploma certificate in Excel, Coursera",
        ],
    )
    def test_an_online_course_diploma_is_not_an_undergraduate_degree(self, text):
        assert find_education_levels(text) == set()

    def test_a_course_line_does_not_hide_a_real_diploma_on_another_line(self):
        text = "Diploma in Mechanical Engineering, 2022\nPython course on Udemy"

        assert find_education_levels(text) == {"UG"}


class TestAge:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Age: 22", 22),
            ("Age - 23 years", 23),
            ("I am 21 years old", 21),
            ("Aged 24", 24),
            ("A 22-year-old graduate", 22),
        ],
    )
    def test_reads_a_stated_age(self, text, expected):
        assert find_age(text) == expected

    def test_no_age_reads_as_none(self):
        assert find_age("3 years of experience") is None

    def test_an_implausible_age_is_ignored(self):
        assert find_age("Age: 7") is None


class TestDateOfBirth:
    @pytest.mark.parametrize(
        "text",
        [
            "DOB: 12/03/2003",
            "Date of Birth - 12-03-2003",
            "D.O.B. 12.03.2003",
            "Date of birth: 12 March 2003",
            "Born on 12th Mar 2003",
            "DOB: March 12, 2003",
            "DOB 2003-03-12",
        ],
    )
    def test_reads_common_formats_day_first(self, text):
        assert find_date_of_birth(text) == datetime.date(2003, 3, 12)

    def test_no_dob_reads_as_none(self):
        assert find_date_of_birth("Jan 2023 - Present") is None

    def test_an_impossible_date_is_ignored(self):
        assert find_date_of_birth("DOB: 31/02/2003") is None


class TestContacts:
    def test_emails_are_lowercased_and_deduplicated(self):
        text = "Aarav.Mehta@College.edu | aarav.mehta@college.edu, alt: am@gmail.com"

        assert find_emails(text) == ["aarav.mehta@college.edu", "am@gmail.com"]

    @pytest.mark.parametrize(
        "text",
        ["+91 98765 43210", "+91-9876543210", "09876543210", "98765-43210", "9876543210"],
    )
    def test_indian_mobile_numbers_normalise_to_ten_digits(self, text):
        assert find_phones(text) == ["9876543210"]

    def test_a_prn_or_year_is_not_a_phone(self):
        assert find_phones("PRN 240200057, batch 2026, roll 1234567890123") == []


class TestCgpa:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("CGPA: 8.45", 8.45),
            ("CGPA 8.45/10", 8.45),
            ("Cumulative GPA: 7.9 / 10", 7.9),
            ("CPI - 9.1", 9.1),
            ("8.2 CGPA", 8.2),
            ("B.Tech, Sai University (GPA 8.0)", 8.0),
        ],
    )
    def test_reads_a_ten_point_cgpa(self, text, expected):
        assert find_cgpa(text) == expected

    def test_a_degree_percentage_converts_at_nine_point_five(self):
        assert find_cgpa("B.Tech in Civil Engineering, aggregate 76%") == 8.0

    def test_school_percentages_are_not_a_cgpa(self):
        assert find_cgpa("Class XII (HSC): 92%\nClass X (SSC): 95%") is None

    def test_a_four_point_scale_is_not_guessed(self):
        assert find_cgpa("GPA 3.6/4.0") is None

    def test_no_cgpa_reads_as_none(self):
        assert find_cgpa("B.Tech in Computer Engineering") is None

    def test_prose_with_a_percentage_is_not_a_cgpa(self):
        assert find_cgpa("I will be 100% committed to the role") is None


class TestAnAgeCueDoesNotSwallowAClaim:
    """F1: an age cue near a real experience claim used to discard the claim."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Age: 22, Experience: 2 years", 2.0),
            ("I am having 2 years of experience in Java", 2.0),
            ("DOB 12/03/2003 Experience 2 years", 2.0),
            ("Name: X  Age: 23  Total Exp: 1 year", 1.0),
            ("I am working since 3 years as developer", 3.0),
            ("I am 2 years experienced in Java", 2.0),
        ],
    )
    def test_the_claim_is_read(self, text, expected):
        assert find_experience_years(text) == expected

    @pytest.mark.parametrize("text", ["I am 21 years, a fresher", "Age: 22 years, Experience: none"])
    def test_an_age_directly_after_its_cue_is_still_an_age(self, text):
        assert find_experience_years(text) == 0.0


class TestMoreStudyDurations:
    """m1: degree words beyond the plan's cue list mark a study duration."""

    @pytest.mark.parametrize(
        "text",
        [
            "3 years Diploma in Mechanical Engineering",
            "Completed 4 years of engineering",
            "4 years of graduation",
            "2 years MBA",
            "4 year B.E. in IT",
        ],
    )
    def test_a_degree_length_is_not_experience(self, text):
        assert find_experience_years(text) == 0.0

    def test_an_engineering_job_is_still_experience(self):
        assert find_experience_years("3 years of experience in software engineering") == 3.0


class TestMoreDateFormats:
    """m2: two-digit years, longer experience headers, year-only starts."""

    def test_an_apostrophe_year_reads_as_twenty_something(self):
        assert find_experience("Software Intern, Jan'23 - Present", today=TODAY).years == 3.8

    def test_apostrophe_years_on_both_sides(self):
        text = "EXPERIENCE\nWeb Developer Intern (May'24 - Jul'24)"

        assert find_experience(text, today=TODAY).years == 0.2

    def test_a_month_slash_two_digit_year(self):
        assert find_experience("Intern, 5/24 - 7/24", today=TODAY).years == 0.2

    @pytest.mark.parametrize("header", ["WORK EXPERIENCE AND INTERNSHIPS", "INTERNSHIP DETAILS"])
    def test_an_unlisted_experience_header_ends_the_education_section(self, header):
        text = (
            "EDUCATION\nB.Tech, XYZ, 2021 - 2025\n"
            f"{header}\nWeb Developer Intern, Jun 2024 - Aug 2024"
        )

        assert find_experience(text, today=TODAY).years == 0.2

    def test_a_prose_line_mentioning_experience_is_not_a_header(self):
        text = "Hands-on experience\nDeveloper Intern at Loadstar, 06/2024 - 08/2024"

        assert find_experience(text, today=TODAY).years == 0.2

    def test_a_year_only_start_outside_a_section_does_not_count(self):
        assert find_experience("Developer, 2024 - Present", today=TODAY).years == 0.0

    def test_a_year_only_start_inside_a_section_counts(self):
        text = "WORK EXPERIENCE\nDeveloper, 2024 - Present"

        assert find_experience(text, today=TODAY).years == 2.8  # Jan 2024 .. Oct 2026


class TestMoreEducationForms:
    """m3."""

    @pytest.mark.parametrize("text", ["M.E (Civil)", "M.E in Structural Engineering, 2025"])
    def test_an_me_without_a_final_dot_is_a_masters(self, text):
        assert find_education_levels(text) == {"Masters"}

    @pytest.mark.parametrize("text", ["Masterclass on React (Udemy)", "Certified Scrum Master"])
    def test_master_as_part_of_another_word_or_title_is_not_a_degree(self, text):
        assert find_education_levels(text) == set()

    def test_post_graduation_is_a_masters(self):
        assert find_education_levels("Post graduation in Management") == {"Masters"}

    def test_a_masters_spelled_with_s_is_still_read(self):
        assert find_education_levels("Masters in Data Science") == {"Masters"}


class TestMoreVerificationFacts:
    """m4."""

    def test_a_bare_gpa_of_four_or_less_could_be_a_four_point_scale(self):
        assert find_cgpa("GPA: 3.8") is None

    def test_a_semester_gpa_is_not_the_cgpa(self):
        assert find_cgpa("Pursuing B.Tech, SGPA 9.2 (Sem 5)") is None

    def test_an_uppercase_be_line_is_a_degree_line(self):
        assert find_cgpa("BE: 78.4 %") == 8.25

    @pytest.mark.parametrize("text", ["+91 987 654 3210", "9876 543 210"])
    def test_other_phone_groupings_are_found(self, text):
        assert find_phones(text) == ["9876543210"]


class TestCraftedTextStaysFast:
    """R1: the upload pre-fill runs synchronously, so crafted text must not
    stall a worker. Each of these took between 4 and 400+ seconds."""

    def test_crafted_inputs_finish_in_under_two_seconds(self):
        import time

        from app.matching.engine import MatchingEngine

        inputs = [
            "experience 2 years " * 2000,
            "1" + " " * 20000,
            "cgpa" + " " * 20000,
            "a" * 20000 + "@" + "b" * 20000,
        ]
        started = time.perf_counter()
        for text in inputs:
            MatchingEngine.regex_facts(text, TODAY)
            find_education_levels(text)
        assert time.perf_counter() - started < 2.0

    def test_a_repeated_claim_is_still_read(self):
        assert find_experience_years("experience 2 years " * 2000) == 2.0

    def test_text_past_the_cap_is_not_read(self):
        from app.extraction.facts import MAX_EXTRACT_CHARS

        text = "x " * (MAX_EXTRACT_CHARS // 2) + "5 years of experience"

        assert find_experience_years(text) == 0.0
