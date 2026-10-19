"""
Similarity backend selection for the matching engine.

The PRD specifies spaCy `en_core_web_md` for semantic similarity. That model
is a 40MB download, so the engine treats it as the preferred backend rather
than a hard requirement: when it is absent (a clean checkout, a slim CI
image) a TF-IDF cosine backend takes over and everything downstream keeps
working. Both satisfy the same interface -- one method, `similarity(a, b)`
returning a float in [0, 1] -- so callers never branch on which is live.

Selected by MATCHING_BACKEND:
    auto   (default) spaCy if importable and the model is present, else TF-IDF
    spacy  force spaCy; raise if unavailable
    tfidf  force TF-IDF
"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache

from app.config import settings

logger = logging.getLogger(__name__)


class SimilarityBackend:
    """Interface every backend implements."""

    name: str = "base"
    detail: str = ""

    #: Sensible starting threshold for THIS backend. The two backends do not
    #: share a scale -- averaged word vectors cluster in the high 0.8s while
    #: TF-IDF cosine over two documents rarely passes 0.3 -- so a single
    #: hardcoded 0.6 would pass everybody on one and nobody on the other.
    #: Screening callers may still override the threshold per request.
    suggested_threshold: float = 0.6

    def similarity(self, text_a: str, text_b: str) -> float:
        raise NotImplementedError


class SpacyBackend(SimilarityBackend):
    """
    Cosine similarity between spaCy document vectors (the PRD's choice).

    One change from the prototype's `doc_a.similarity(doc_b)`: the document
    vector is averaged over content words only -- no stopwords, punctuation
    or numbers. Averaging everything let "the/and/with/for" dominate both
    vectors, so a mechanical-design resume scored 0.92 against a backend job
    description and the whole sample set fell inside a 0.06 band. Filtering
    to content words widens that band to 0.16 on the same set, which is what
    makes an adjustable threshold worth adjusting.
    """

    name = "spacy"
    suggested_threshold = 0.85

    def __init__(self, model_name: str):
        import spacy  # imported lazily: optional dependency

        self._model_name = model_name
        try:
            self._nlp = spacy.load(model_name, exclude=["parser", "ner"])
        except OSError as exc:
            raise RuntimeError(
                f"spaCy model '{model_name}' is not installed. "
                f"Run: python -m spacy download {model_name}"
            ) from exc

        if not self._nlp.vocab.vectors_length:
            raise RuntimeError(
                f"spaCy model '{model_name}' ships no word vectors, so similarity "
                f"would be meaningless. Use a model such as en_core_web_md."
            )
        self.detail = f"{model_name} ({self._nlp.vocab.vectors_length}d vectors, content words)"
        self._lock = threading.Lock()

    def _content_vector(self, text: str):
        """Mean vector over content words; None when the text carries none."""
        import numpy as np

        with self._lock:
            # spaCy pipelines are not thread-safe, and Django's dev server and
            # gunicorn threads can both land here.
            doc = self._nlp(text)

        vectors = [
            token.vector
            for token in doc
            if token.has_vector
            and token.is_alpha
            and not token.is_stop
            and not token.is_punct
            and not token.is_space
        ]
        if not vectors:
            # Nothing but stopwords: fall back to whatever the document has
            # rather than reporting a confident zero.
            return doc.vector if doc.has_vector else None
        return np.mean(vectors, axis=0)

    def similarity(self, text_a: str, text_b: str) -> float:
        if not text_a or not text_b:
            return 0.0

        import numpy as np

        vector_a = self._content_vector(text_a)
        vector_b = self._content_vector(text_b)
        if vector_a is None or vector_b is None:
            return 0.0

        norms = float(np.linalg.norm(vector_a) * np.linalg.norm(vector_b))
        if norms == 0.0:
            return 0.0
        # Vector cosine can go slightly negative; the portal treats similarity
        # as a 0-1 score, so clamp rather than surface a negative match.
        return max(0.0, float(np.dot(vector_a, vector_b) / norms))


class TfidfBackend(SimilarityBackend):
    """
    Fallback: TF-IDF over word 1- and 2-grams, cosine between the two texts.

    Vectorising only the pair being compared keeps this stateless and makes
    each call independent of whatever else has been scored -- important
    because bulk screening must give the same score for a candidate whether
    it ran alone or inside a batch.
    """

    name = "tfidf"
    detail = "scikit-learn TfidfVectorizer, word 1-2 grams"
    # Two documents sharing vocabulary rarely exceed ~0.3 here, so the usable
    # threshold sits an order of magnitude below spaCy's.
    suggested_threshold = 0.10

    def similarity(self, text_a: str, text_b: str) -> float:
        if not text_a or not text_b:
            return 0.0

        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vectorizer = TfidfVectorizer(
            stop_words="english", ngram_range=(1, 2), sublinear_tf=True
        )
        try:
            matrix = vectorizer.fit_transform([text_a, text_b])
        except ValueError:
            # Both texts were entirely stop words / punctuation.
            return 0.0
        return max(0.0, float(cosine_similarity(matrix[0:1], matrix[1:2])[0][0]))


@lru_cache(maxsize=None)
def get_backend(name: str | None = None) -> SimilarityBackend:
    """
    Return the process-wide similarity backend.

    Cached because loading the spaCy model is the expensive part -- one load
    per process, reused across every request and bulk-screening run.
    """
    requested = (name or settings.matching_backend).strip().lower()
    model_name = settings.spacy_model

    if requested == "tfidf":
        return TfidfBackend()

    if requested == "spacy":
        return SpacyBackend(model_name)

    if requested != "auto":
        raise ValueError(
            f"Unknown MATCHING_BACKEND '{requested}'. Use auto, spacy, or tfidf."
        )

    try:
        return SpacyBackend(model_name)
    except (ImportError, RuntimeError) as exc:
        logger.warning(
            "spaCy backend unavailable (%s); falling back to TF-IDF similarity.", exc
        )
        return TfidfBackend()


def backend_info() -> dict:
    """Which backend is live -- reported by /api/health."""
    try:
        backend = get_backend()
        return {
            "ok": True,
            "backend": backend.name,
            "detail": backend.detail,
            "suggested_threshold": backend.suggested_threshold,
        }
    except Exception as exc:  # pragma: no cover - misconfiguration only
        return {"ok": False, "backend": "none", "detail": str(exc)}
