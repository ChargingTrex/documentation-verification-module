"""The regex name reader: the name is the first name-like line at the top."""

import pytest

from app.extraction.name import find_name


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Aarav Mehta\naarav@college.edu | PRN2022CS001\n\nSUMMARY", "Aarav Mehta"),
        ("RESUME\n\nSana Qureshi\nsana@x.com", "Sana Qureshi"),
        ("CURRICULUM VITAE\nKabir Nair\n", "Kabir Nair"),
        ("S.SOUNDHAR\nSoftware Engineer\n+91 98765 43210", "S.SOUNDHAR"),
        ("Dr. Rajan Sathiya\nProfessor", "Dr. Rajan Sathiya"),
        ("Ananya Krishnan Iyer\n", "Ananya Krishnan Iyer"),
    ],
)
def test_the_name_is_read(text, expected):
    assert find_name(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "SKILLS\nPython, Django",                     # a bare heading
        "Software Engineer\n3 years of experience",  # a job title
        "Email: a@b.com\nPhone: 9876543210",          # contact lines
        "Backend Developer Intern\nAcme",             # role words
        "",
        "S\n.\nS\nO\nU",                              # a PDF that came out one glyph per line
    ],
)
def test_lines_that_are_not_a_name_are_skipped(text):
    assert find_name(text) is None


def test_only_the_top_of_the_resume_is_searched():
    text = "\n".join(["Objective: a role"] + ["Python, Django"] * 10 + ["Aarav Mehta"])

    assert find_name(text) is None
