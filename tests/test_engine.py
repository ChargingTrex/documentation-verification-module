"""
The matching engine: parsing, scoring, hard filters and bulk screening.

These are the Phase 2 checkpoint assertions. They are written to hold on
either similarity backend -- CI runs TF-IDF, a developer machine with the
spaCy model runs spaCy, and the two do not share a numeric scale -- so
everything here is stated in relative terms or against the engine's own
threshold rather than against hardcoded scores.
"""

import pytest

from app.matching.engine import MatchingEngine, ScreeningResult
from app.extraction.text import ResumeParseError
from tests.fixtures.samples import RELEVANT_KEYS, SAMPLE_JOB_DESCRIPTION, SAMPLE_RESUMES


class TestParsing:
    @pytest.mark.parametrize("sample", SAMPLE_RESUMES, ids=lambda s: s.key)
    def test_extracted_values_match_the_hand_checked_reference(
        self, engine, sample_resume_dir, sample
    ):
        """The Phase 2 checkpoint: experience and education read off a real
        PDF/DOCX file equal the values a human read off the same resume."""
        with (sample_resume_dir / sample.filename).open("rb") as handle:
            extracted = engine.parse_resume(handle, sample.filename)

        assert extracted.experience_years == sample.expected_experience_years
        assert extracted.education_levels == set(sample.expected_education_levels)

    def test_parsing_reports_the_highest_level_and_its_implications(
        self, engine, sample_resume_dir
    ):
        with (sample_resume_dir / "sana_qureshi_data.docx").open("rb") as handle:
            extracted = engine.parse_resume(handle, "sana_qureshi_data.docx")

        assert extracted.highest_education_level == "Masters"
        assert extracted.effective_education_levels == {"Masters", "UG"}

    def test_an_unreadable_file_raises(self, engine):
        import io

        with pytest.raises(ResumeParseError):
            engine.parse_resume(io.BytesIO(b"nonsense"), "resume.pdf")


class TestSimilarity:
    def test_identical_text_scores_higher_than_unrelated_text(self, engine):
        text = "Django REST Framework developer with PostgreSQL experience"
        unrelated = "Pastry chef specialising in French desserts"

        assert engine.similarity(text, text) > engine.similarity(text, unrelated)

    def test_similarity_stays_within_zero_and_one(self, engine, sample_texts):
        for text in sample_texts.values():
            score = engine.similarity(text, SAMPLE_JOB_DESCRIPTION)
            assert 0.0 <= score <= 1.0

    def test_empty_text_scores_zero(self, engine):
        assert engine.similarity("", SAMPLE_JOB_DESCRIPTION) == 0.0
        assert engine.similarity(SAMPLE_JOB_DESCRIPTION, "") == 0.0

    def test_scoring_is_independent_of_the_batch_it_ran_in(self, engine, sample_texts):
        """A candidate must score the same alone as inside a bulk run,
        otherwise a shortlist depends on who else applied."""
        alone = engine.score_one(
            "backend_engineer", sample_texts["backend_engineer"], SAMPLE_JOB_DESCRIPTION
        )
        in_batch = engine.screen(
            sample_texts, SAMPLE_JOB_DESCRIPTION, similarity_threshold=0.0
        )
        batched = next(r for r in in_batch.ranked if r.identifier == "backend_engineer")

        assert alone.similarity_score == batched.similarity_score


class TestRanking:
    @pytest.fixture
    def unfiltered(self, engine, sample_texts) -> ScreeningResult:
        return engine.screen(sample_texts, SAMPLE_JOB_DESCRIPTION, similarity_threshold=0.0)

    def test_the_two_relevant_resumes_outrank_the_three_irrelevant_ones(self, unfiltered):
        """Phase 2 smoke test step 3."""
        order = [result.identifier for result in unfiltered.ranked]

        assert set(order[:2]) == set(RELEVANT_KEYS)

    def test_results_are_sorted_best_first(self, unfiltered):
        scores = [result.similarity_score for result in unfiltered.ranked]

        assert scores == sorted(scores, reverse=True)

    def test_every_result_carries_its_extracted_attributes(self, unfiltered):
        for result in unfiltered.ranked:
            assert result.extracted.experience_years >= 0
            assert isinstance(result.extracted.education_levels, set)

    def test_nobody_is_lost_between_the_three_groups(self, unfiltered, sample_texts):
        assert unfiltered.considered == len(sample_texts)


class TestThreshold:
    def test_raising_the_threshold_shortlists_fewer_people(self, engine, sample_texts):
        """Phase 2 smoke test step 5."""
        scores = sorted(
            (
                engine.similarity(text, SAMPLE_JOB_DESCRIPTION)
                for text in sample_texts.values()
            ),
            reverse=True,
        )
        # Pick two thresholds from the observed scores so the assertion holds
        # on whichever backend is live.
        permissive, strict = scores[-1], scores[1]

        loose = engine.screen(sample_texts, SAMPLE_JOB_DESCRIPTION, similarity_threshold=permissive)
        tight = engine.screen(sample_texts, SAMPLE_JOB_DESCRIPTION, similarity_threshold=strict)

        assert len(loose.ranked) == len(sample_texts)
        assert len(tight.ranked) == 2
        assert len(tight.below_threshold) == len(sample_texts) - 2

    def test_a_threshold_above_every_score_shortlists_nobody(self, engine, sample_texts):
        result = engine.screen(sample_texts, SAMPLE_JOB_DESCRIPTION, similarity_threshold=1.01)

        assert result.ranked == []
        assert len(result.below_threshold) == len(sample_texts)

    def test_the_threshold_is_configurable_not_hardcoded(self, engine, settings):
        settings.default_similarity_threshold = 0.42

        assert MatchingEngine().default_threshold == 0.42

    def test_an_unset_threshold_falls_back_to_the_backend_suggestion(self, engine, settings):
        settings.default_similarity_threshold = None
        built = MatchingEngine()

        assert built.default_threshold > 0
        assert built.default_threshold == built._backend.suggested_threshold

    def test_the_engine_default_separates_relevant_from_irrelevant(self, engine, sample_texts):
        """The shipped default is not just any number: on the reference set it
        shortlists exactly the two relevant resumes."""
        result = engine.screen(sample_texts, SAMPLE_JOB_DESCRIPTION)

        assert {r.identifier for r in result.ranked} == set(RELEVANT_KEYS)


class TestHardFilters:
    def test_minimum_experience_excludes_regardless_of_similarity(self, engine, sample_texts):
        """Phase 2 smoke test step 4."""
        result = engine.screen(
            sample_texts,
            SAMPLE_JOB_DESCRIPTION,
            similarity_threshold=0.0,
            min_experience_years=2.0,
        )

        excluded = {r.identifier for r in result.excluded}
        assert excluded == {"frontend_intern", "marketing_executive"}
        # Excluded candidates appear in no other group, whatever they scored.
        assert excluded.isdisjoint({r.identifier for r in result.ranked})
        assert excluded.isdisjoint({r.identifier for r in result.below_threshold})

    def test_an_exclusion_states_its_reason(self, engine, sample_texts):
        result = engine.screen(
            sample_texts,
            SAMPLE_JOB_DESCRIPTION,
            similarity_threshold=0.0,
            min_experience_years=2.0,
        )
        reason = next(r.excluded_by for r in result.excluded if r.identifier == "frontend_intern")

        assert "2 years" in reason
        assert "0.5" in reason

    def test_an_excluded_candidate_is_never_scored(self, engine, sample_texts):
        result = engine.screen(
            sample_texts,
            SAMPLE_JOB_DESCRIPTION,
            similarity_threshold=0.0,
            min_experience_years=10.0,
        )

        assert all(r.similarity_score == 0.0 for r in result.excluded)
        assert all(r.passed_threshold is False for r in result.excluded)

    def test_required_education_excludes_candidates_without_it(self, engine, sample_texts):
        result = engine.screen(
            sample_texts,
            SAMPLE_JOB_DESCRIPTION,
            similarity_threshold=0.0,
            required_education={"PG"},
        )

        assert result.ranked == []
        assert len(result.excluded) == len(sample_texts)

    def test_a_masters_candidate_satisfies_an_undergraduate_requirement(
        self, engine, sample_texts
    ):
        """The data engineer's resume names only her M.Tech."""
        result = engine.screen(
            sample_texts,
            SAMPLE_JOB_DESCRIPTION,
            similarity_threshold=0.0,
            required_education={"UG"},
        )

        assert "data_engineer" in {r.identifier for r in result.ranked}

    def test_filters_combine(self, engine, sample_texts):
        result = engine.screen(
            sample_texts,
            SAMPLE_JOB_DESCRIPTION,
            similarity_threshold=0.0,
            min_experience_years=2.0,
            required_education={"Masters"},
        )

        assert {r.identifier for r in result.ranked} == {"data_engineer"}

    def test_no_filters_means_nobody_is_excluded(self, engine, sample_texts):
        result = engine.screen(sample_texts, SAMPLE_JOB_DESCRIPTION, similarity_threshold=0.0)

        assert result.excluded == []


class TestSerialisation:
    def test_a_screening_result_serialises_for_the_api(self, engine, sample_texts):
        payload = engine.screen(
            sample_texts, SAMPLE_JOB_DESCRIPTION, min_experience_years=2.0
        ).as_dict()

        assert payload["considered"] == len(sample_texts)
        assert payload["shortlisted"] == len(payload["ranked"])
        first = payload["ranked"][0]
        assert {"identifier", "similarity_score", "experience_years", "education_levels"} <= first.keys()
