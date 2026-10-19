"""The HTTP surface: CV upload, document/subject lookups, bulk screening."""

from pathlib import Path

from tests.fixtures.samples import RELEVANT_KEYS, SAMPLE_JOB_DESCRIPTION

FIXTURES = Path(__file__).parent / "fixtures" / "resumes"


def _upload(api, name="aarav_mehta_backend.pdf", **form):
    with (FIXTURES / name).open("rb") as handle:
        return api.post("/documents/cv", files={"file": (name, handle, "application/pdf")}, data=form)


class TestHealth:
    def test_health_names_the_live_pieces(self, api):
        body = api.get("/health").json()

        assert body["status"] == "ok"
        assert body["ocr_engine"] == "stub"
        assert body["llm"]["enabled"] is False
        assert body["matching"]["backend"] in {"tfidf", "spacy"}

    def test_the_ui_is_served_at_the_root(self, api):
        response = api.get("/")

        assert response.status_code == 200
        assert "Document Verifier" in response.text


class TestCvUpload:
    def test_a_fixture_resume_comes_back_as_a_record_with_sources(self, api):
        response = _upload(api, subject_type="student", external_ref="PRN2022CS001")

        assert response.status_code == 200, response.text
        body = response.json()
        cv = body["cv"]
        assert body["subject_id"] and body["document_id"]
        assert cv["emails"] == ["aarav.mehta@college.edu"]
        assert cv["experience_years"] == 3.0
        assert cv["education_levels"] == ["UG"]
        assert cv["extraction_source"] == "regex"
        assert cv["llm_model"] is None
        assert cv["field_sources"]["emails"] == "regex"
        assert cv["field_sources"]["full_name"] == "none"

    def test_the_record_is_persisted_and_readable_back(self, api):
        uploaded = _upload(api, subject_type="employee").json()

        document = api.get(f"/documents/{uploaded['document_id']}").json()
        subject = api.get(f"/subjects/{uploaded['subject_id']}").json()

        assert document["extraction"]["emails"] == ["aarav.mehta@college.edu"]
        assert document["extraction_source"] == "regex"
        assert subject["type"] == "employee"
        assert [d["kind"] for d in subject["documents"]] == ["cv"]
        assert subject["latest_verification"] is None

    def test_an_upload_without_a_subject_is_allowed(self, api):
        body = _upload(api).json()

        assert body["subject_id"] is None

    def test_an_existing_subject_can_be_named(self, api):
        first = _upload(api, subject_type="student").json()

        second = _upload(api, name="kabir_nair_frontend.pdf", subject_id=first["subject_id"]).json()

        assert second["subject_id"] == first["subject_id"]
        assert len(api.get(f"/subjects/{first['subject_id']}").json()["documents"]) == 2

    def test_an_unknown_subject_is_404(self, api):
        assert _upload(api, subject_id="nope").status_code == 404

    def test_a_bad_subject_type_is_422(self, api):
        assert _upload(api, subject_type="alien").status_code == 422

    def test_a_wrong_file_type_is_400(self, api):
        response = api.post("/documents/cv", files={"file": ("notes.txt", b"hello", "text/plain")})

        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]

    def test_an_unreadable_pdf_is_422(self, api):
        response = api.post("/documents/cv", files={"file": ("cv.pdf", b"nonsense", "application/pdf")})

        assert response.status_code == 422

    def test_an_unknown_document_is_404(self, api):
        assert api.get("/documents/missing").status_code == 404


class TestScreen:
    def test_the_relevant_resumes_rank_first(self, api, sample_texts):
        response = api.post(
            "/match/screen",
            json={"candidates": sample_texts, "job_description": SAMPLE_JOB_DESCRIPTION, "similarity_threshold": 0},
        )

        body = response.json()
        assert response.status_code == 200, response.text
        assert body["considered"] == len(sample_texts)
        assert {r["identifier"] for r in body["ranked"][:2]} == set(RELEVANT_KEYS)

    def test_hard_filters_exclude_with_a_reason(self, api, sample_texts):
        body = api.post(
            "/match/screen",
            json={
                "candidates": sample_texts,
                "job_description": SAMPLE_JOB_DESCRIPTION,
                "similarity_threshold": 0,
                "min_experience_years": 2,
            },
        ).json()

        excluded = {r["identifier"]: r["excluded_by"] for r in body["excluded_results"]}
        assert set(excluded) == {"frontend_intern", "marketing_executive"}
        assert "2 years" in excluded["frontend_intern"]

    def test_a_bad_education_level_is_422(self, api):
        response = api.post(
            "/match/screen",
            json={"candidates": {"a": "x"}, "job_description": "y", "required_education": ["Diploma"]},
        )

        assert response.status_code == 422
