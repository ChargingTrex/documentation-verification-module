"""School marks a resume states: the 10th and 12th lines."""

from app.extraction.school import find_school_marks


def test_both_stages_with_percentages_boards_and_years():
    text = (
        "EDUCATION\n"
        "B.Tech in Computer Engineering, Sai University, 2022 - 2026, CGPA 8.4\n"
        "HSC, Tamil Nadu State Board, 2021 - 91%\n"
        "Class X (CBSE), 2019 - 92.4%\n"
    )

    marks = find_school_marks(text)

    assert marks["twelfth"] == {"percentage": 91.0, "cgpa": None, "board": "Tamil Nadu State Board", "year": 2021}
    assert marks["tenth"] == {"percentage": 92.4, "cgpa": None, "board": "CBSE", "year": 2019}


def test_a_cbse_tenth_cgpa():
    marks = find_school_marks("10th Standard, CBSE, 2018 - CGPA 9.6")

    assert marks["tenth"]["cgpa"] == 9.6 and marks["tenth"]["percentage"] is None


def test_the_figure_on_the_next_line_counts():
    marks = find_school_marks("Higher Secondary (12th)\nState Board, 2021 - Aggregate 88%")

    assert marks["twelfth"]["percentage"] == 88.0


def test_a_twelfth_line_is_not_also_read_as_tenth():
    marks = find_school_marks("Class XII, CBSE 2020: 85%")

    assert marks["twelfth"]["percentage"] == 85.0
    assert marks["tenth"] is None


def test_lines_without_a_figure_give_nothing():
    assert find_school_marks("Completed 12th standard at Delhi Public School") == {"tenth": None, "twelfth": None}


def test_percentages_outside_the_plausible_range_are_dropped():
    assert find_school_marks("10th: 12%") == {"tenth": None, "twelfth": None}


def test_empty():
    assert find_school_marks("") == {"tenth": None, "twelfth": None}
