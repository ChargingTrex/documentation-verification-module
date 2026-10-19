"""The Aadhaar and PAN parsers, the Verhoeff check, and the OCR engine plumbing."""

import json

import pytest

from app.ocr import verhoeff
from app.ocr.aadhaar import parse_aadhaar
from app.ocr.engine import OcrLine, StubEngine, rows
from app.ocr.pan import parse_pan
from tests.fixtures.make_idcards import AARAV, CARDS, aadhaar_number, spaced

PARSERS = {"aadhaar": parse_aadhaar, "pan": parse_pan}


class TestVerhoeff:
    def test_a_generated_number_validates(self):
        assert verhoeff.validate(aadhaar_number("23456789012"))

    def test_one_wrong_digit_fails(self):
        number = aadhaar_number("23456789012")
        wrong = number[:5] + str((int(number[5]) + 1) % 10) + number[6:]

        assert not verhoeff.validate(wrong)

    def test_spaces_are_ignored(self):
        assert verhoeff.validate(spaced(AARAV))

    def test_empty_is_invalid(self):
        assert not verhoeff.validate("")


class TestFixtureCards:
    """Every synthetic card parses to its manifest, through the stub engine."""

    @pytest.mark.parametrize("card", CARDS, ids=lambda c: c.key)
    def test_the_card_parses_to_its_expected_values(self, card, card_dir):
        lines = StubEngine().read((card_dir / f"{card.key}.png").read_bytes(), f"{card.key}.png")

        facts = PARSERS[card.type](lines, engine_name="stub").as_dict()

        for key, expected in card.expected.items():
            if key == "checks":
                for check, value in expected.items():
                    assert facts["checks"][check] is value, check
            elif key.startswith("address_"):
                assert facts["address"][key.removeprefix("address_")] == expected
            else:
                assert facts[key] == expected, key
        assert facts["ocr_engine"] == "stub"

    def test_the_full_number_never_appears_in_the_record(self, card_dir):
        lines = StubEngine().read((card_dir / "aarav_aadhaar.png").read_bytes(), "aarav_aadhaar.png")

        facts = parse_aadhaar(lines).as_dict()

        dumped = json.dumps(facts)
        assert AARAV not in dumped and spaced(AARAV) not in dumped
        assert f"XXXX XXXX {AARAV[-4:]}" in facts["lines"]

    def test_the_full_pan_never_appears_in_the_record(self, card_dir):
        lines = StubEngine().read((card_dir / "aarav_pan.png").read_bytes(), "aarav_pan.png")

        facts = parse_pan(lines).as_dict()

        assert "ABCPM1234F" not in json.dumps(facts)
        assert "XXXXXX234F" in facts["lines"]

    def test_the_manifest_matches_the_cards(self, card_dir):
        manifest = json.loads((card_dir / "manifest.json").read_text())

        assert set(manifest) == {f"{card.key}.png" for card in CARDS}


class TestMergeAadhaar:
    def _card(self, name, card_dir):
        return parse_aadhaar(StubEngine().read((card_dir / name).read_bytes(), name), engine_name="stub")

    def test_front_and_back_become_one_card(self, card_dir):
        from app.ocr.aadhaar import merge_aadhaar

        merged = merge_aadhaar(self._card("aarav_aadhaar.png", card_dir), self._card("aarav_aadhaar_back.png", card_dir))

        assert merged.sides == ["front", "back"]
        assert merged.full_name == "Aarav Mehta" and merged.gender == "M" and merged.dob == "2003-03-12"
        assert merged.address["pincode"] == "600017"
        assert merged.id_last4 == AARAV[-4:]
        assert merged.checks["aadhaar_sides_agree"] is True and merged.checks["aadhaar_checksum"] is True
        assert merged.lines[0].startswith("front: ") and merged.lines[-1].startswith("back: ")

    def test_sides_of_different_cards_disagree(self, card_dir):
        from app.ocr.aadhaar import merge_aadhaar

        merged = merge_aadhaar(self._card("sana_aadhaar.png", card_dir), self._card("aarav_aadhaar_back.png", card_dir))

        assert merged.checks["aadhaar_sides_agree"] is False
        assert merged.full_name == "Sana Qureshi"

    def test_one_side_passes_through(self, card_dir):
        from app.ocr.aadhaar import merge_aadhaar

        assert merge_aadhaar(self._card("aarav_aadhaar.png", card_dir), None).sides == ["front"]
        assert merge_aadhaar(None, self._card("aarav_aadhaar_back.png", card_dir)).sides == ["back"]

    def test_no_side_is_an_error(self):
        from app.ocr.aadhaar import merge_aadhaar

        with pytest.raises(ValueError):
            merge_aadhaar(None, None)


class TestAadhaarHeuristics:
    def _parse(self, *lines):
        return parse_aadhaar([OcrLine(text=line, score=0.9) for line in lines])

    def test_a_vid_is_not_mistaken_for_the_number(self):
        facts = self._parse("Aarav Mehta", "DOB: 12/03/2003", "VID: 9123 4567 8901 2345")

        assert facts.id_last4 is None
        assert facts.checks["aadhaar_number_found"] is False

    def test_a_misread_number_fails_the_checksum_but_still_yields_last4(self):
        bad = AARAV[:-1] + str((int(AARAV[-1]) + 1) % 10)
        facts = self._parse("Aarav Mehta", "DOB: 12/03/2003", spaced(bad))

        assert facts.id_last4 == bad[-4:]
        assert facts.checks["aadhaar_checksum"] is False

    def test_label_lines_are_never_the_name(self):
        facts = self._parse("Government of India", "Aadhaar - Aam Aadmi ka Adhikar", "Sana Qureshi", "DOB: 01/01/2000")

        assert facts.full_name == "Sana Qureshi"

    @pytest.mark.parametrize("header", ["GOVERNMENTOF INDIA", "Govemment of lndia", "Unique ldentification Authority"])
    def test_a_garbled_heading_is_never_the_name(self, header):
        facts = self._parse(header, "Sana Qureshi", "DOB: 01/01/2000")

        assert facts.full_name == "Sana Qureshi"

    def test_the_hindi_line_is_skipped(self):
        facts = self._parse("कबीर नायर", "Kabir Nair", "Year of Birth: 2004", "MALE")

        assert facts.full_name == "Kabir Nair"
        assert facts.year_of_birth == 2004 and facts.dob is None

    def test_a_dob_on_the_next_line_is_read(self):
        facts = self._parse("Kabir Nair", "DOB", "04/07/2004")

        assert facts.dob == "2004-07-04"

    def test_the_number_is_not_read_as_a_mobile(self):
        facts = self._parse("Aarav Mehta", spaced(AARAV), "Mobile: 9876543210")

        assert facts.phones == ["9876543210"]

    def test_an_impossible_date_is_dropped(self):
        assert self._parse("X Y", "DOB: 31/02/2003").dob is None

    def test_confidence_is_the_mean_score(self):
        facts = parse_aadhaar([OcrLine("Aarav Mehta", 0.9), OcrLine("DOB: 12/03/2003", 0.7)])

        assert facts.ocr_confidence == 0.8


class TestPanHeuristics:
    def _parse(self, *lines):
        return parse_pan([OcrLine(text=line, score=0.9) for line in lines])

    def test_a_company_pan_is_flagged_not_individual(self):
        facts = self._parse("INCOME TAX DEPARTMENT", "ABCCM1234F", "Name", "ACME PVT LTD")

        assert facts.checks["pan_individual"] is False
        assert facts.full_name == "ACME PVT LTD"

    def test_no_pan_sets_the_format_check_false(self):
        facts = self._parse("INCOME TAX DEPARTMENT", "Name", "AARAV MEHTA")

        assert facts.checks["pan_format"] is False and facts.id_last4 is None

    def test_a_label_merged_with_its_value_by_ocr(self):
        facts = self._parse("Name AARAV MEHTA", "Father's Name RAJESH MEHTA")

        assert facts.full_name == "AARAV MEHTA" and facts.father_name == "RAJESH MEHTA"

    @pytest.mark.parametrize(
        "header",
        [
            "INCOME TAX DEPARTMENT GOVT.OFINDIA",   # two headings joined into one row
            "lNCOME TAX DEPARTMENT",                 # a lowercase L for the I
            "INCOMETAX DEPARTMENT",
            "GOVT OFINDIA",
            "Permanent Account Number Card",
            "PERMANENT ACCOUNTNUMBER CARD",
        ],
    )
    def test_a_printed_heading_is_never_the_name_however_garbled(self, header):
        facts = self._parse(header, "BEHPM9319H", "/Father's Name", "NEELAMEGAM", "06/06/1992 /Signature")

        assert facts.full_name != header.strip()
        assert facts.father_name == "NEELAMEGAM"

    def test_with_the_name_label_lost_the_line_above_the_father_label_is_the_name(self):
        """What a poor read of the real card looks like: garbage at the top,
        the father's label intact, the name just above it."""
        facts = self._parse("CEN OV IA", "ge", "erar", "E19H", "PRAVEEN BALAJI N", "/Father's Name",
                            "NEELAMEGAM", "06/06/1992 R/Signature")

        assert facts.full_name == "PRAVEEN BALAJI N"
        assert facts.father_name == "NEELAMEGAM"

    def test_garbage_capitals_alone_do_not_become_a_name_over_the_father_anchor(self):
        facts = self._parse("CEN OV IA", "erar", "/Father's Name", "NEELAMEGAM")

        # Nothing name-like sits right above the father label, so the old-layout
        # fallback runs; the father's line is excluded from it.
        assert facts.father_name == "NEELAMEGAM"
        assert facts.full_name != "NEELAMEGAM"

    def test_lowercase_lines_are_not_pan_names(self):
        facts = self._parse("some lowercase words", "Name", "AARAV MEHTA")

        assert facts.full_name == "AARAV MEHTA"


class TestRows:
    def test_boxes_on_one_row_are_joined_left_to_right(self):
        lines = [
            OcrLine("12/03/2003", 0.9, [[120, 100], [260, 100], [260, 130], [120, 130]]),
            OcrLine("DOB:", 0.8, [[10, 101], [100, 101], [100, 131], [10, 131]]),
            OcrLine("Aarav Mehta", 0.95, [[10, 40], [200, 40], [200, 70], [10, 70]]),
        ]

        joined = rows(lines)

        assert [line.text for line in joined] == ["Aarav Mehta", "DOB: 12/03/2003"]
        assert joined[1].score == 0.8

    def test_lines_without_boxes_keep_their_order(self):
        lines = [OcrLine("b"), OcrLine("a")]

        assert [line.text for line in rows(lines)] == ["b", "a"]


class TestStubEngine:
    def test_a_file_without_metadata_or_sidecar_is_an_error(self):
        from app.ocr.engine import OCRError

        with pytest.raises(OCRError):
            StubEngine().read(b"not an image", "x.png")

    def test_explicit_lines_win(self):
        assert [l.text for l in StubEngine(["a", "b"]).read(b"", "x.png")] == ["a", "b"]
