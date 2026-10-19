"""Name comparison: normalisation, word order, middle names, initials, thresholds."""

import pytest

from app.verify.names import compare, normalise


class TestNormalise:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("Aarav Mehta", "AARAV MEHTA"),
            ("  Mr. Aarav   Mehta ", "AARAV MEHTA"),
            ("Dr. S. Kumar", "S KUMAR"),
            ("Smt. Sana Qureshi", "SANA QURESHI"),
            ("José Álvarez", "JOSE ALVAREZ"),
            ("AARAV MEHTA", "AARAV MEHTA"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalise(self, value, expected):
        assert normalise(value) == expected


class TestCompare:
    def test_the_same_name_in_different_case_is_an_exact_match(self):
        result = compare("Aarav Mehta", "AARAV MEHTA")

        assert result.score == 100 and result.verdict == "match" and result.method == "exact"

    def test_word_order_does_not_matter(self):
        assert compare("Mehta Aarav", "Aarav Mehta").verdict == "match"

    def test_a_missing_middle_name_is_still_a_match(self):
        assert compare("Aarav Kumar Mehta", "AARAV MEHTA").verdict == "match"

    def test_an_ocr_slip_lands_in_match_or_review_not_mismatch(self):
        result = compare("Sana Qureshi", "SANA QURESHl")  # a lowercase L for an I

        assert result.verdict in {"match", "review"}
        assert result.score >= 85

    def test_a_different_person_is_a_mismatch(self):
        result = compare("Kabir Nair", "AARAV MEHTA")

        assert result.verdict == "mismatch"
        assert result.score < 70

    def test_an_initial_cannot_confirm_a_full_name(self):
        result = compare("A. Mehta", "AARAV MEHTA")

        assert result.verdict == "review"

    def test_initials_on_the_card_side_are_capped_too(self):
        result = compare("Rajan Sathiya", "R SATHIYA")

        assert result.verdict == "review"
        assert result.score < 85

    def test_a_capped_score_says_so(self):
        """Letters that line up well enough to 'match' are held at review."""
        result = compare("S. Kumar", "S KUMAR R")

        assert result.score < 85 and result.method == "initials_capped"

    def test_a_missing_name_is_a_mismatch_with_a_reason(self):
        result = compare(None, "AARAV MEHTA")

        assert result.verdict == "mismatch" and result.method == "missing" and result.score == 0

    def test_thresholds_come_from_settings(self, settings):
        settings.name_match_threshold = 99
        settings.name_review_threshold = 95

        assert compare("Aarav Kumar Mehta", "AARAV MEHTA").verdict == "match"  # subset -> 100
        assert compare("Sana Qureshi", "SANA QURESHl").verdict in {"review", "mismatch"}

    def test_the_result_serialises(self):
        result = compare("Aarav Mehta", "AARAV MEHTA").as_dict()

        assert set(result) == {"cv", "id", "cv_normalised", "id_normalised", "score", "verdict", "method"}
