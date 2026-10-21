"""Marksheets and transcripts: detection, the regex parser, the model path, the record."""

import json

import pytest

from app.academic.parser import detect_academic_type, mask_rolls, parse_academic
from app.academic.service import academic_record, analyse_academic
from app.ocr.engine import OCRError
from tests.fakes import FakeLLMClient
from tests.fixtures.make_academic import SHEETS


def _sheet(key):
    return next(s for s in SHEETS if s.key == key)


class TestFixtureSheets:
    """Every synthetic sheet reads to its manifest through the real file path (stub OCR / PDF text)."""

    @pytest.mark.parametrize("sheet", SHEETS, ids=lambda s: s.key)
    def test_the_sheet_reads_to_its_expected_values(self, sheet, academic_dir):
        path = academic_dir / f"{sheet.key}.{sheet.format}"

        record = analyse_academic(path.read_bytes(), path.name, sheet.type)

        assert record["type"] == sheet.type
        assert record["text_source"] == ("pdf" if sheet.format == "pdf" else "ocr")
        assert record["extraction_source"] == "regex"
        for key, expected in sheet.expected.items():
            if key == "checks":
                for check, value in expected.items():
                    assert record["checks"][check] is value, f"{sheet.key}: {check}"
            elif key == "subjects":
                assert len(record["subjects"]) == expected, sheet.key
            elif key.endswith("_contains"):
                assert expected in (record[key.removesuffix("_contains")] or "").lower(), sheet.key
            else:
                assert record[key] == expected, f"{sheet.key}: {key}"

    def test_roll_numbers_never_appear_in_full(self, academic_dir):
        record = analyse_academic((academic_dir / "aarav_10th.png").read_bytes(), "aarav_10th.png", "marksheet_10")

        dumped = json.dumps(record)
        assert "1234567" not in dumped
        assert record["roll_last4"] == "4567"
        assert any("XXXX4567" in line for line in record["lines"])

    def test_the_manifest_matches(self, academic_dir):
        manifest = json.loads((academic_dir / "manifest.json").read_text())

        assert set(manifest) == {f"{s.key}.{s.format}" for s in SHEETS}


class TestDetect:
    def test_each_fixture_is_typed_from_its_text(self):
        for sheet in SHEETS:
            assert detect_academic_type(sheet.lines) == sheet.type, sheet.key

    def test_a_tenth_sheet_uploaded_as_twelfth_is_flagged(self):
        facts = parse_academic(_sheet("aarav_10th").lines, "marksheet_12")

        assert facts.detected_type == "marksheet_10"
        assert facts.checks["document_type_matches"] is False

    def test_plain_text_is_none(self):
        assert detect_academic_type(["Aarav Mehta", "Python, Django"]) is None

    def test_higher_secondary_is_not_mistaken_for_secondary_school(self):
        lines = ["BOARD OF HIGHER SECONDARY EDUCATION", "HIGHER SECONDARY EXAMINATION 2021", "ENGLISH 085"]

        assert detect_academic_type(lines) == "marksheet_12"


class TestParserRules:
    def test_a_total_without_rows_gives_a_computed_percentage(self):
        facts = parse_academic(["SSLC EXAMINATION", "Name: ARJUN K", "Total Marks: 450 out of 500"], "marksheet_10")

        assert facts.percentage == 90.0 and facts.percentage_source == "computed"

    def test_rows_out_of_a_stated_maximum(self):
        facts = parse_academic(["CLASS X", "Name: ARJUN K", "ENGLISH 45/50", "MATHS 48/50", "SCIENCE 40/50"], "marksheet_10")

        assert facts.subjects[0]["max_marks"] == 50.0
        assert facts.percentage == pytest.approx(88.67, abs=0.01)

    def test_heading_rows_are_not_subjects(self):
        facts = parse_academic(["Roll No 123456", "SUBJECT MARKS GRADE", "Total 180", "ENGLISH 90", "MATHS 90"], "marksheet_10")

        assert [s["name"] for s in facts.subjects] == ["ENGLISH", "MATHS"]

    def test_a_label_with_the_value_on_the_next_line(self):
        facts = parse_academic(["Candidate's Name", "ARJUN RAMESH K", "Father's Name", "RAMESH"], "marksheet_10")

        assert facts.full_name == "ARJUN RAMESH K" and facts.father_name == "RAMESH"

    def test_a_transcript_cgpa_comes_from_the_sgpas_when_not_printed(self):
        facts = parse_academic(["ANNA UNIVERSITY", "Name: ARJUN K", "Semester 1 SGPA: 8.0", "Semester 2 SGPA: 9.0"], "transcript")

        assert facts.cgpa == 8.5 and facts.sgpa == [8.0, 9.0]

    def test_mask_rolls(self):
        assert mask_rolls("Register No: 2101234") == "Register No: XXXX1234"
        assert mask_rolls("ENGLISH 091") == "ENGLISH 091"

    def test_a_failed_result(self):
        assert parse_academic(["CLASS X", "Result: FAIL"], "marksheet_10").result == "FAIL"


class TestModelPath:
    def _reply(self, **overrides):
        reply = {
            "document_type": "marksheet_10", "full_name": "Aarav Mehta", "father_name": "Rajesh Mehta",
            "mother_name": None, "roll_number": "1234567", "date_of_birth": "2003-03-12",
            "board_or_university": "CBSE", "institution": "Delhi Public School", "year": 2019,
            "subjects": [{"name": "English", "marks": 91, "max_marks": 100, "grade": "A2"},
                         {"name": "Maths", "marks": 95, "max_marks": 100, "grade": "A1"},
                         {"name": "Science", "marks": 94, "max_marks": 100, "grade": "A1"}],
            "total_marks": 280, "max_total": 300, "percentage": 93.3, "cgpa": None, "sgpa": [], "result": "PASS",
        }
        reply.update(overrides)
        return reply

    def test_the_model_reading_fills_the_record_and_is_badged_llm(self, academic_dir):
        path = academic_dir / "aarav_10th.png"
        client = FakeLLMClient([self._reply()])

        record = analyse_academic(path.read_bytes(), path.name, "marksheet_10", client=client)

        assert record["extraction_source"] == "llm" and record["llm_model"] == "fake-llama"
        assert record["full_name"] == "Aarav Mehta" and record["field_sources"]["full_name"] == "llm"
        assert record["roll_last4"] == "4567" and record["field_sources"]["roll_last4"] == "regex"
        assert "previous reply was invalid" not in client.prompts[0][1]

    def test_the_percentage_is_recomputed_from_the_rows_not_taken_from_the_model(self):
        from app.academic.parser import parse_academic

        regex = parse_academic(["CLASS X", "Name: AARAV MEHTA"], "marksheet_10")
        facts = self._reply(percentage=99.0)  # the model's arithmetic is wrong on purpose

        record = academic_record("marksheet_10", regex, facts, {"text_source": "ocr"})

        assert record["percentage"] == 99.0 and record["percentage_source"] == "stated"
        assert record["percentage_computed"] == pytest.approx(93.33, abs=0.01)
        assert record["checks"]["percentage_matches_rows"] is False

    def test_a_down_model_falls_back_to_regex(self, academic_dir):
        path = academic_dir / "aarav_10th.png"

        record = analyse_academic(path.read_bytes(), path.name, "marksheet_10", client=FakeLLMClient(down=True))

        assert record["extraction_source"] == "regex" and record["full_name"] == "AARAV MEHTA"

    def test_a_messy_reply_is_coerced(self):
        from app.llm.academic import normalise_academic_reply

        data = normalise_academic_reply({"document_type": "Class XII marksheet", "year": "2020", "percentage": "88.5%",
                                         "sgpa": "8.1, 8.3", "subjects": [{"name": "Maths", "marks": "95/100"}]})

        assert data["document_type"] == "marksheet_12" and data["year"] == 2020
        assert data["percentage"] == 88.5 and data["sgpa"] == [8.1, 8.3]
        assert data["subjects"][0]["marks"] == 95.0


class TestUnreadable:
    def test_an_image_the_stub_cannot_read_is_an_error(self):
        with pytest.raises(OCRError):
            analyse_academic(b"not an image", "x.png", "marksheet_10")
