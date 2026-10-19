"""Backend selection: spaCy preferred, TF-IDF fallback, both interchangeable."""

import pytest

from app.matching.backends import SpacyBackend, TfidfBackend, backend_info, get_backend
from tests.fixtures.samples import SAMPLE_JOB_DESCRIPTION


def _spacy_available() -> bool:
    try:
        SpacyBackend("en_core_web_md")
        return True
    except Exception:
        return False


class TestSelection:
    def test_tfidf_can_be_forced(self):
        assert get_backend("tfidf").name == "tfidf"

    def test_an_unknown_backend_name_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown MATCHING_BACKEND"):
            get_backend("word2vec")

    def test_auto_falls_back_to_tfidf_when_spacy_is_missing(self, monkeypatch):
        def explode(*args, **kwargs):
            raise RuntimeError("spaCy model 'en_core_web_md' is not installed.")

        monkeypatch.setattr("app.matching.backends.SpacyBackend", explode)
        get_backend.cache_clear()
        try:
            assert get_backend("auto").name == "tfidf"
        finally:
            get_backend.cache_clear()

    def test_a_model_without_vectors_is_refused(self, monkeypatch):
        """en_core_web_sm ships no vectors, so similarity would be noise."""
        pytest.importorskip("spacy")

        class VectorlessNlp:
            class vocab:  # noqa: N801 - mirrors spaCy's attribute shape
                vectors_length = 0

        monkeypatch.setattr("spacy.load", lambda *a, **k: VectorlessNlp())
        with pytest.raises(RuntimeError, match="ships no word vectors"):
            SpacyBackend("en_core_web_sm")

    def test_the_backend_is_cached_so_the_model_loads_once(self):
        assert get_backend("tfidf") is get_backend("tfidf")

    def test_health_reports_the_live_backend(self):
        info = backend_info()

        assert info["ok"] is True
        assert info["backend"] in {"spacy", "tfidf"}
        assert info["suggested_threshold"] > 0


class TestBackendBehaviour:
    """Whatever the backend, these properties must hold."""

    @pytest.fixture(params=["tfidf", "spacy"])
    def backend(self, request):
        if request.param == "spacy" and not _spacy_available():
            pytest.skip("spaCy model not installed on this machine")
        return get_backend(request.param)

    def test_similarity_is_bounded(self, backend):
        score = backend.similarity("Python Django backend developer", SAMPLE_JOB_DESCRIPTION)

        assert 0.0 <= score <= 1.0

    def test_similarity_is_symmetric(self, backend):
        a, b = "Django REST APIs and PostgreSQL", "PostgreSQL and Django REST APIs experience"

        assert backend.similarity(a, b) == pytest.approx(backend.similarity(b, a), abs=1e-6)

    def test_empty_input_scores_zero(self, backend):
        assert backend.similarity("", "anything") == 0.0
        assert backend.similarity("anything", "") == 0.0

    def test_relevant_text_outscores_irrelevant_text(self, backend):
        relevant = "Backend developer, 3 years Python and Django, PostgreSQL schema design"
        irrelevant = "Pastry chef, four years of laminated doughs and sugar work"

        assert backend.similarity(relevant, SAMPLE_JOB_DESCRIPTION) > backend.similarity(
            irrelevant, SAMPLE_JOB_DESCRIPTION
        )

    def test_a_text_of_only_stopwords_does_not_crash(self, backend):
        assert 0.0 <= backend.similarity("the and of to", SAMPLE_JOB_DESCRIPTION) <= 1.0

    def test_each_backend_suggests_a_threshold_on_its_own_scale(self, backend):
        assert 0.0 < backend.suggested_threshold < 1.0
