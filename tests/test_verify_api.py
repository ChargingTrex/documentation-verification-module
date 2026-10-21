"""POST /verify end to end: Aadhaar (one or two sides), PAN, or both, on the stub OCR engine."""

import json
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


class TestWrongSlot:
    def test_a_pan_in_the_aadhaar_slot_is_flagged_not_hidden(self, api, card_dir, llm_reads_the_cv):
        body = _verify(api, card_dir, aadhaar_front="aarav_pan.png").json()

        card = body["id_cards"]["aadhaar"]
        assert card["detected_type"] == "pan"
        assert {c["name"]: c["passed"] for c in body["checks"]}["card_type_matches"] is False


CV_LINES = [
    "Aarav Mehta",
    "aarav.mehta@college.edu | +91 98765 43210",
    "Date of Birth: 12/03/2003",
    "EDUCATION",
    "B.E. Computer Science and Engineering, Anna University, 2022 - 2026, CGPA: 8.4",
    "HSC, Tamil Nadu State Board, 2021 - 91%",
    "Class X (CBSE), 2019 - 92%",
]


@pytest.fixture
def cv_with_marks(tmp_path):
    from tests.fixtures.make_resumes import write_pdf

    path = tmp_path / "aarav_marks.pdf"
    write_pdf(path, CV_LINES)
    return path


def _verify_academic(api, academic_dir, cv_path, form=None, **sheets):
    handles = [cv_path.open("rb")]
    files = {"cv": ("cv.pdf", handles[0], "application/pdf")}
    for key, name in sheets.items():
        handle = (academic_dir / name).open("rb")
        handles.append(handle)
        files[key] = (name, handle, "application/pdf" if name.endswith(".pdf") else "image/png")
    data = {"form": json.dumps(form)} if form else {}
    try:
        return api.post("/verify", files=files, data=data)
    finally:
        for handle in handles:
            handle.close()


class TestAcademic:
    def test_marksheets_and_transcript_verify_the_cvs_claims(self, api, academic_dir, cv_with_marks):
        response = _verify_academic(api, academic_dir, cv_with_marks, marksheet_10="aarav_10th.png",
                                    marksheet_12="aarav_12th.png", transcript="aarav_transcript.pdf")

        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body["academic"]) == {"marksheet_10", "marksheet_12", "transcript"}
        assert body["cv"]["school"]["tenth"]["percentage"] == 92.0
        assert body["cv"]["cgpa"] == 8.4
        checks = {c["name"]: c for c in body["checks"]}
        assert checks["cgpa_consistent"]["passed"] is True            # CV 8.4 vs transcript 8.4
        assert checks["tenth_marks_consistent"]["passed"] is True     # CV 92 vs sheet 92.0
        assert checks["twelfth_marks_consistent"]["passed"] is True   # CV 91 vs sheet 91.0 (computed)
        assert checks["tenth_year_consistent"]["passed"] is True
        assert checks["academic_years_in_order"]["passed"] is True    # 2019 < 2021 < 2026
        assert checks["dob_consistent"]["passed"] is True
        assert checks["marksheet_10_name_match"]["passed"] is True
        assert checks["transcript_document_type_matches"]["passed"] is True
        # No ID card: the verdict comes from the academic documents.
        assert body["name_match"]["verdict"] == "match"

    def test_an_inflated_cv_claim_is_caught(self, api, academic_dir, tmp_path):
        from tests.fixtures.make_resumes import write_pdf

        path = tmp_path / "inflated.pdf"
        write_pdf(path, [line.replace("CGPA: 8.4", "CGPA: 9.1").replace("2019 - 92%", "2019 - 95%") for line in CV_LINES])

        body = _verify_academic(api, academic_dir, path, marksheet_10="aarav_10th.png", transcript="aarav_transcript.pdf").json()

        checks = {c["name"]: c for c in body["checks"]}
        assert checks["cgpa_consistent"]["passed"] is False and "CV 9.1" in checks["cgpa_consistent"]["detail"]
        assert checks["tenth_marks_consistent"]["passed"] is False

    def test_a_sheet_whose_rows_do_not_add_up_is_flagged(self, api, academic_dir, cv_with_marks):
        body = _verify_academic(api, academic_dir, cv_with_marks, marksheet_12="sana_12th_inflated.png").json()

        checks = {c["name"]: c for c in body["checks"]}
        assert checks["marksheet_12_percentage_matches_rows"]["passed"] is False
        assert body["academic"]["marksheet_12"]["percentage_computed"] == 82.6
        assert checks["marksheet_12_name_match"]["passed"] is False  # Sana's sheet, Aarav's CV

    def test_a_sheet_in_the_wrong_slot_is_flagged(self, api, academic_dir, cv_with_marks):
        body = _verify_academic(api, academic_dir, cv_with_marks, marksheet_12="aarav_10th.png").json()

        assert body["academic"]["marksheet_12"]["detected_type"] == "marksheet_10"
        assert {c["name"]: c["passed"] for c in body["checks"]}["marksheet_12_document_type_matches"] is False

    def test_the_academic_upload_endpoint(self, api, academic_dir):
        with (academic_dir / "aarav_transcript.pdf").open("rb") as handle:
            response = api.post("/documents/academic", files={"file": ("t.pdf", handle, "application/pdf")},
                                data={"type": "transcript", "subject_type": "student"})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["kind"] == "transcript" and body["academic"]["cgpa"] == 8.4
        assert body["academic"]["text_source"] == "pdf"
        stored = api.get(f"/documents/{body['document_id']}").json()
        assert stored["extraction"]["sgpa"] == [8.2, 8.6, 8.4, 8.4]

    def test_a_bad_academic_type_is_422(self, api, academic_dir):
        with (academic_dir / "aarav_10th.png").open("rb") as handle:
            response = api.post("/documents/academic", files={"file": ("m.png", handle, "image/png")},
                                data={"type": "degree"})

        assert response.status_code == 422


class TestRegistrationForm:
    FORM = {"full_name": "Aarav Mehta", "date_of_birth": "2003-03-12", "email": "aarav.mehta@college.edu",
            "phone": "+91 98765 43210", "cgpa": 8.4, "tenth_percentage": 92.0, "tenth_year": 2019,
            "twelfth_percentage": 91.0, "twelfth_year": 2021}

    def test_the_form_is_a_third_source_for_every_figure(self, api, academic_dir, cv_with_marks):
        body = _verify_academic(api, academic_dir, cv_with_marks, form=self.FORM, marksheet_10="aarav_10th.png",
                                marksheet_12="aarav_12th.png", transcript="aarav_transcript.pdf").json()

        assert body["form"]["cgpa"] == 8.4
        checks = {c["name"]: c for c in body["checks"]}
        assert checks["cgpa_consistent"]["passed"] is True
        assert "form 8.4" in checks["cgpa_consistent"]["detail"] and "transcript 8.4" in checks["cgpa_consistent"]["detail"]
        assert checks["tenth_marks_consistent"]["passed"] is True
        assert checks["form_vs_cv_name_match"]["passed"] is True
        assert checks["form_email_on_cv"]["passed"] is True
        assert checks["form_phone_on_cv"]["passed"] is True
        assert checks["dob_consistent"]["passed"] is True
        assert body["name_matches"]["form_vs_cv"]["verdict"] == "match"

    def test_a_form_cgpa_that_disagrees_names_the_pair(self, api, academic_dir, cv_with_marks):
        form = {**self.FORM, "cgpa": 9.1}

        body = _verify_academic(api, academic_dir, cv_with_marks, form=form, transcript="aarav_transcript.pdf").json()

        check = {c["name"]: c for c in body["checks"]}["cgpa_consistent"]
        assert check["passed"] is False
        assert "form/CV" in check["detail"] and "form/transcript" in check["detail"]

    def test_the_form_compares_with_the_id_cards_too(self, api, card_dir, academic_dir, cv_with_marks):
        with cv_with_marks.open("rb") as cv_file, (card_dir / "aarav_aadhaar.png").open("rb") as card_file:
            body = api.post("/verify", files={"cv": ("cv.pdf", cv_file, "application/pdf"),
                                              "aadhaar_front": ("a.png", card_file, "image/png")},
                            data={"form": json.dumps({"full_name": "Aarav Mehta", "date_of_birth": "2003-03-12"})}).json()

        assert body["name_matches"]["form_vs_aadhaar"]["verdict"] == "match"
        assert {c["name"]: c["passed"] for c in body["checks"]}["dob_consistent"] is True

    def test_a_form_that_is_not_json_is_422(self, api, card_dir, cv_with_marks):
        with cv_with_marks.open("rb") as cv_file, (card_dir / "aarav_pan.png").open("rb") as card_file:
            response = api.post("/verify", files={"cv": ("cv.pdf", cv_file, "application/pdf"),
                                                  "pan": ("p.png", card_file, "image/png")},
                                data={"form": "not json"})

        assert response.status_code == 422

    def test_verify_documents_takes_the_form_as_json(self, api, academic_dir, cv_with_marks):
        with cv_with_marks.open("rb") as handle:
            cv = api.post("/documents/cv", files={"file": ("cv.pdf", handle, "application/pdf")},
                          data={"subject_type": "student"}).json()
        with (academic_dir / "aarav_transcript.pdf").open("rb") as handle:
            tr = api.post("/documents/academic", files={"file": ("t.pdf", handle, "application/pdf")},
                          data={"type": "transcript", "subject_id": cv["subject_id"]}).json()

        body = api.post("/verify/documents", json={"cv_document_id": cv["document_id"],
                                                   "transcript_document_id": tr["document_id"],
                                                   "form": {"cgpa": 8.4}}).json()

        assert {c["name"]: c["passed"] for c in body["checks"]}["cgpa_consistent"] is True


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
