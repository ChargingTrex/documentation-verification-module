"""POST /verify end to end: Aadhaar (one or two sides), PAN, or both, on the stub OCR engine."""

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


def _verify(api, card_dir, cv="aarav_mehta_backend.pdf", **files_and_form):
    """files_and_form: aadhaar_front= / aadhaar_back= / pan= card file names, plus form fields."""
    handles = [(RESUMES / cv).open("rb")]
    files = {"cv": (cv, handles[0], "application/pdf")}
    form = {}
    for key, value in files_and_form.items():
        if key in ("aadhaar_front", "aadhaar_back", "pan"):
            handle = (card_dir / value).open("rb")
            handles.append(handle)
            files[key] = (value, handle, "image/png")
        else:
            form[key] = value
    try:
        return api.post("/verify", files=files, data=form)
    finally:
        for handle in handles:
            handle.close()


class TestAadhaar:
    def test_front_only_matches_the_name(self, api, card_dir, llm_reads_the_cv):
        response = _verify(api, card_dir, aadhaar_front="aarav_aadhaar.png", subject_type="student",
                           external_ref="PRN2022CS001")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name_match"]["verdict"] == "match"
        assert set(body["id_cards"]) == {"aadhaar"}
        assert body["id_cards"]["aadhaar"]["sides"] == ["front"]
        assert body["name_matches"]["aadhaar"]["id"] == "Aarav Mehta"
        assert [d["kind"] for d in body["documents"]] == ["cv", "aadhaar"]
        assert body["cv"]["field_sources"]["full_name"] == "llm"

    def test_both_sides_merge_into_one_card(self, api, card_dir, llm_reads_the_cv):
        body = _verify(api, card_dir, aadhaar_front="aarav_aadhaar.png", aadhaar_back="aarav_aadhaar_back.png").json()

        card = body["id_cards"]["aadhaar"]
        assert card["sides"] == ["front", "back"]
        assert card["full_name"] == "Aarav Mehta" and card["dob"] == "2003-03-12"
        assert card["address"]["pincode"] == "600017" and card["address"]["state"] == "Tamil Nadu"
        checks = {c["name"]: c["passed"] for c in body["checks"]}
        assert checks["aadhaar_sides_agree"] is True
        assert checks["aadhaar_checksum"] is True
        assert [(d["kind"], d["side"]) for d in body["documents"]] == [("cv", None), ("aadhaar", "front"), ("aadhaar", "back")]

    def test_the_back_of_a_different_card_is_flagged(self, api, card_dir, llm_reads_the_cv):
        body = _verify(api, card_dir, aadhaar_front="sana_aadhaar.png", aadhaar_back="aarav_aadhaar_back.png").json()

        assert {c["name"]: c["passed"] for c in body["checks"]}["aadhaar_sides_agree"] is False

    def test_back_only_has_no_name_to_match(self, api, card_dir, llm_reads_the_cv):
        body = _verify(api, card_dir, aadhaar_back="aarav_aadhaar_back.png").json()

        assert body["id_cards"]["aadhaar"]["sides"] == ["back"]
        assert body["name_match"]["verdict"] == "mismatch" and body["name_match"]["method"] == "missing"
        assert body["id_cards"]["aadhaar"]["address"]["pincode"] == "600017"


class TestPan:
    def test_pan_only(self, api, card_dir, llm_reads_the_cv):
        body = _verify(api, card_dir, pan="aarav_pan.png").json()

        assert set(body["id_cards"]) == {"pan"}
        assert body["name_match"]["verdict"] == "match"
        assert body["id_cards"]["pan"]["father_name"] == "RAJESH MEHTA"


class TestBothCards:
    def test_both_cards_compare_with_the_cv_and_each_other(self, api, card_dir, llm_reads_the_cv):
        body = _verify(api, card_dir, aadhaar_front="aarav_aadhaar.png", aadhaar_back="aarav_aadhaar_back.png",
                       pan="aarav_pan.png").json()

        assert set(body["id_cards"]) == {"aadhaar", "pan"}
        assert set(body["name_matches"]) == {"aadhaar", "pan", "aadhaar_vs_pan"}
        assert body["name_match"]["verdict"] == "match"
        checks = {c["name"]: c["passed"] for c in body["checks"]}
        assert checks["aadhaar_vs_pan_name_match"] is True
        assert checks["dob_consistent"] is True

    def test_the_overall_verdict_is_the_worst_card(self, api, card_dir, llm_reads_the_cv):
        body = _verify(api, card_dir, aadhaar_front="aarav_aadhaar.png", pan="sana_pan.png").json()

        assert body["name_matches"]["aadhaar"]["verdict"] == "match"
        assert body["name_matches"]["pan"]["verdict"] == "mismatch"
        assert body["name_match"]["verdict"] == "mismatch"
        checks = {c["name"]: c["passed"] for c in body["checks"]}
        assert checks["aadhaar_vs_pan_name_match"] is False
        assert checks["dob_consistent"] is False

    def test_a_different_persons_cv_mismatches_every_card(self, api, card_dir, llm_reads_the_cv):
        body = _verify(api, card_dir, cv="kabir_nair_frontend.pdf", aadhaar_front="aarav_aadhaar.png",
                       pan="aarav_pan.png").json()

        assert body["name_match"]["verdict"] == "mismatch"
        assert body["name_matches"]["aadhaar_vs_pan"]["verdict"] == "match"


class TestInputs:
    def test_no_card_at_all_is_422(self, api, card_dir):
        assert _verify(api, card_dir).status_code == 422

    def test_without_a_model_the_top_line_name_still_verifies(self, api, card_dir):
        body = _verify(api, card_dir, aadhaar_front="aarav_aadhaar.png").json()

        assert body["name_match"]["verdict"] == "match"
        assert body["cv"]["field_sources"]["full_name"] == "regex"

    def test_a_cv_with_no_readable_name_says_so(self, api, card_dir, tmp_path):
        from tests.fixtures.make_resumes import write_pdf

        path = tmp_path / "anon.pdf"
        write_pdf(path, ["SKILLS", "Python, Django", "EXPERIENCE", "Intern, Acme, Jan 2024 - Mar 2024"])
        with path.open("rb") as cv_file, (card_dir / "aarav_aadhaar.png").open("rb") as card_file:
            body = api.post(
                "/verify",
                files={"cv": ("anon.pdf", cv_file, "application/pdf"),
                       "aadhaar_front": ("c.png", card_file, "image/png")},
            ).json()

        assert body["name_match"]["verdict"] == "mismatch" and body["name_match"]["method"] == "missing"
        assert {c["name"]: c["passed"] for c in body["checks"]}["cv_name_found"] is False


class TestStorage:
    def test_the_verification_is_stored_and_readable_back(self, api, card_dir, llm_reads_the_cv):
        body = _verify(api, card_dir, aadhaar_front="aarav_aadhaar.png", pan="aarav_pan.png",
                       subject_type="employee").json()

        stored = api.get(f"/verifications/{body['verification_id']}").json()
        subject = api.get(f"/subjects/{body['subject_id']}").json()

        assert stored["name_match"] == body["name_match"]
        assert sorted(d["kind"] for d in subject["documents"]) == ["aadhaar", "cv", "pan"]
        assert subject["latest_verification"]["name_match"]["verdict"] == "match"

    def test_separately_uploaded_documents_can_be_verified_afterwards(self, api, card_dir, llm_reads_the_cv):
        with (RESUMES / "aarav_mehta_backend.pdf").open("rb") as handle:
            cv = api.post("/documents/cv", files={"file": ("cv.pdf", handle, "application/pdf")},
                          data={"subject_type": "student"}).json()
        with (card_dir / "aarav_aadhaar.png").open("rb") as handle:
            front = api.post("/documents/id", files={"file": ("f.png", handle, "image/png")},
                             data={"type": "aadhaar", "side": "front", "subject_id": cv["subject_id"]}).json()
        with (card_dir / "aarav_aadhaar_back.png").open("rb") as handle:
            back = api.post("/documents/id", files={"file": ("b.png", handle, "image/png")},
                            data={"type": "aadhaar", "side": "back", "subject_id": cv["subject_id"]}).json()

        body = api.post("/verify/documents", json={
            "cv_document_id": cv["document_id"],
            "aadhaar_front_document_id": front["document_id"],
            "aadhaar_back_document_id": back["document_id"],
        }).json()

        assert body["name_match"]["verdict"] == "match"
        assert body["id_cards"]["aadhaar"]["sides"] == ["front", "back"]
        assert body["id_cards"]["aadhaar"]["address"]["pincode"] == "600017"

    def test_verifying_the_wrong_kind_of_document_is_404(self, api, card_dir):
        with (card_dir / "aarav_pan.png").open("rb") as handle:
            card = api.post("/documents/id", files={"file": ("card.png", handle, "image/png")},
                            data={"type": "pan"}).json()

        response = api.post("/verify/documents", json={"cv_document_id": card["document_id"],
                                                       "pan_document_id": card["document_id"]})

        assert response.status_code == 404

    def test_a_pan_has_no_back_side(self, api, card_dir):
        with (card_dir / "aarav_pan.png").open("rb") as handle:
            response = api.post("/documents/id", files={"file": ("card.png", handle, "image/png")},
                                data={"type": "pan", "side": "back"})

        assert response.status_code == 422

    def test_an_unknown_verification_is_404(self, api):
        assert api.get("/verifications/nope").status_code == 404
