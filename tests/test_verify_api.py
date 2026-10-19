"""POST /verify end to end, on the stub OCR engine and a fake model."""

from pathlib import Path

import pytest

from app.matching import engine as engine_module
from tests.fakes import FakeLLMClient, resume_reply

RESUMES = Path(__file__).parent / "fixtures" / "resumes"


@pytest.fixture
def llm_reads_the_cv(monkeypatch):
    """Make the engine see a model that reads the CV's name, without a server."""
    real = engine_module.MatchingEngine.analyse_resume

    def with_fake(self, text, *, client=None, today=None):
        name = "Aarav Mehta" if "Aarav" in text else "Kabir Nair"
        return real(self, text, client=FakeLLMClient([resume_reply(full_name=name, emails=[])]), today=today)

    monkeypatch.setattr(engine_module.MatchingEngine, "analyse_resume", with_fake)


def _verify(api, card_dir, cv="aarav_mehta_backend.pdf", card="aarav_aadhaar.png", id_type="aadhaar", **form):
    with (RESUMES / cv).open("rb") as cv_file, (card_dir / card).open("rb") as card_file:
        return api.post(
            "/verify",
            files={"cv": (cv, cv_file, "application/pdf"), "id_card": (card, card_file, "image/png")},
            data={"id_type": id_type, **form},
        )


class TestVerify:
    def test_matching_documents_verify_as_a_match(self, api, card_dir, llm_reads_the_cv):
        response = _verify(api, card_dir, subject_type="student", external_ref="PRN2022CS001")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name_match"]["verdict"] == "match"
        assert body["name_match"]["cv"] == "Aarav Mehta" and body["name_match"]["id"] == "Aarav Mehta"
        assert body["subject_type"] == "student"
        assert body["cv"]["field_sources"]["full_name"] == "llm"
        assert body["cv"]["field_sources"]["emails"] == "regex"
        assert body["id_card"]["ocr_engine"] == "stub"
        assert {c["name"]: c["passed"] for c in body["checks"]}["aadhaar_checksum"] is True

    def test_a_different_persons_cv_is_a_mismatch(self, api, card_dir, llm_reads_the_cv):
        body = _verify(api, card_dir, cv="kabir_nair_frontend.pdf").json()

        assert body["name_match"]["verdict"] == "mismatch"
        assert body["name_match"]["cv"] == "Kabir Nair"

    def test_without_a_model_the_cv_has_no_name_and_the_verdict_says_so(self, api, card_dir):
        body = _verify(api, card_dir).json()

        assert body["name_match"]["verdict"] == "mismatch"
        assert body["name_match"]["method"] == "missing"
        assert {c["name"]: c["passed"] for c in body["checks"]}["cv_name_found"] is False

    def test_a_pan_card_works_too(self, api, card_dir, llm_reads_the_cv):
        body = _verify(api, card_dir, card="aarav_pan.png", id_type="pan").json()

        assert body["name_match"]["verdict"] == "match"
        assert body["id_card"]["type"] == "pan"

    def test_the_verification_is_stored_and_readable_back(self, api, card_dir, llm_reads_the_cv):
        body = _verify(api, card_dir, subject_type="employee").json()

        stored = api.get(f"/verifications/{body['verification_id']}").json()
        subject = api.get(f"/subjects/{body['subject_id']}").json()

        assert stored["name_match"] == body["name_match"]
        assert sorted(d["kind"] for d in subject["documents"]) == ["aadhaar", "cv"]
        assert subject["latest_verification"]["name_match"]["verdict"] == "match"

    def test_two_uploaded_documents_can_be_verified_afterwards(self, api, card_dir, llm_reads_the_cv):
        with (RESUMES / "aarav_mehta_backend.pdf").open("rb") as handle:
            cv = api.post("/documents/cv", files={"file": ("cv.pdf", handle, "application/pdf")},
                          data={"subject_type": "student"}).json()
        with (card_dir / "aarav_aadhaar.png").open("rb") as handle:
            card = api.post("/documents/id", files={"file": ("card.png", handle, "image/png")},
                            data={"type": "aadhaar", "subject_id": cv["subject_id"]}).json()

        body = api.post("/verify/documents", json={"cv_document_id": cv["document_id"],
                                                   "id_document_id": card["document_id"]}).json()

        assert body["name_match"]["verdict"] == "match"
        assert body["subject_id"] == cv["subject_id"]

    def test_verifying_the_wrong_kind_of_document_is_404(self, api, card_dir):
        with (card_dir / "aarav_pan.png").open("rb") as handle:
            card = api.post("/documents/id", files={"file": ("card.png", handle, "image/png")},
                            data={"type": "pan"}).json()

        response = api.post("/verify/documents", json={"cv_document_id": card["document_id"],
                                                       "id_document_id": card["document_id"]})

        assert response.status_code == 404

    def test_a_bad_id_type_is_422(self, api, card_dir):
        assert _verify(api, card_dir, id_type="passport").status_code == 422

    def test_an_unknown_verification_is_404(self, api):
        assert api.get("/verifications/nope").status_code == 404
