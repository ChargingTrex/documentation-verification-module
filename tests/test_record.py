"""`cv_record`: one flat record, and the source of every field."""

import datetime

import pytest

from app.extraction.record import cv_record
from app.matching.engine import MatchingEngine
from tests.fakes import FakeLLMClient, resume_reply

TODAY = datetime.date(2026, 10, 19)

TEXT = """Aarav Mehta
aarav.mehta@college.edu | +91 98765 43210
Address: 12, Gandhi Street, T. Nagar, Chennai - 600017, Tamil Nadu

Education
B.Tech in Computer Engineering, Sai University, 2022 - 2026, CGPA 8.4

Experience
Backend Intern, Acme, Jun 2025 - Aug 2025
"""


@pytest.fixture
def engine():
    return MatchingEngine()


class TestRegexPath:
    def test_every_field_regex_can_read_is_marked_regex(self, engine):
        record = cv_record(engine.analyse_resume(TEXT, today=TODAY))

        assert record["extraction_source"] == "regex"
        assert record["llm_model"] is None
        assert record["emails"] == ["aarav.mehta@college.edu"]
        assert record["phones"] == ["9876543210"]
        assert record["address"]["pincode"] == "600017"
        assert record["education"] == [{"degree": None, "level": "UG"}]
        assert record["cgpa"] == 8.4
        sources = record["field_sources"]
        assert sources["emails"] == sources["phones"] == sources["address"] == "regex"
        assert sources["education"] == sources["cgpa"] == sources["experience_years"] == "regex"

    def test_the_top_line_name_is_regex(self, engine):
        record = cv_record(engine.analyse_resume(TEXT, today=TODAY))

        assert record["full_name"] == "Aarav Mehta"
        assert record["field_sources"]["full_name"] == "regex"

    def test_what_regex_cannot_read_is_marked_none(self, engine):
        nameless = "\n".join(TEXT.split("\n")[1:])  # the same resume without its top line

        record = cv_record(engine.analyse_resume(nameless, today=TODAY))

        assert record["full_name"] is None
        assert record["experience"] == [] and record["skills"] == []
        sources = record["field_sources"]
        assert sources["full_name"] == sources["experience"] == sources["skills"] == "none"


class TestLLMPath:
    def test_model_fields_are_marked_llm_and_contact_stays_regex(self, engine):
        reply = resume_reply(
            full_name="Aarav Mehta",
            phones=["9999999999"],  # the model mis-read it; regex is exact
            address="12 Gandhi Street, T Nagar, Chennai 600017",
            experience=[{"role": "Backend Intern", "organization": "Acme", "start": "2025-06", "end": "2025-08"}],
        )

        record = cv_record(engine.analyse_resume(TEXT, client=FakeLLMClient([reply]), today=TODAY))

        assert record["extraction_source"] == "llm"
        assert record["llm_model"] == "fake-llama"
        assert record["full_name"] == "Aarav Mehta"
        assert record["phones"] == ["9876543210"]
        assert record["address"] == {"raw": "12 Gandhi Street, T Nagar, Chennai 600017", "pincode": "600017", "state": None}
        assert record["experience"][0]["organization"] == "Acme"
        sources = record["field_sources"]
        assert sources["full_name"] == sources["address"] == sources["education"] == sources["experience"] == "llm"
        assert sources["emails"] == sources["phones"] == "regex"
        assert sources["experience_years"] == "llm"
        assert record["experience_years"] == 0.2

    def test_the_model_fills_a_contact_gap_regex_left(self, engine):
        reply = resume_reply(phones=["9999999999"], emails=[])
        text = "Aarav Mehta\nB.Tech, Sai University"

        record = cv_record(engine.analyse_resume(text, client=FakeLLMClient([reply]), today=TODAY))

        assert record["phones"] == ["9999999999"]
        assert record["field_sources"]["phones"] == "llm"
        assert record["emails"] == [] and record["field_sources"]["emails"] == "none"

    def test_the_models_dated_total_beats_a_stated_claim(self, engine):
        """The engine's rule: dates are checkable, a claim is not. The claim
        stays visible in regex_facts/agreement for a reviewer."""
        reply = resume_reply(experience=[{"role": "Engineer", "start": "2024-01", "end": "2024-06"}])
        text = "Engineer with 3 years of experience. Acme, Jan 2024 - Jun 2024."

        record = cv_record(engine.analyse_resume(text, client=FakeLLMClient([reply]), today=TODAY))

        assert record["experience_years"] == 0.5
        assert record["field_sources"]["experience_years"] == "llm"
        assert record["regex_facts"]["experience_years"] == 3.0
        assert record["agreement"]["experience_years"]["agree"] is False

    def test_without_dated_work_the_regex_reading_stands(self, engine):
        text = "Engineer with 3 years of experience."

        record = cv_record(engine.analyse_resume(text, client=FakeLLMClient([resume_reply()]), today=TODAY))

        assert record["experience_years"] == 3.0
        assert record["field_sources"]["experience_years"] == "regex"

    def test_the_model_address_wins_over_the_regex_one(self, engine):
        reply = resume_reply(address="Flat 3B, Baner Road, Pune, Maharashtra 411045")

        record = cv_record(engine.analyse_resume(TEXT, client=FakeLLMClient([reply]), today=TODAY))

        assert record["address"]["state"] == "Maharashtra"
        assert record["regex_facts"]["address"]["pincode"] == "600017"
        assert record["field_sources"]["address"] == "llm"
