"""Bulk screening through the ported matching engine."""

from __future__ import annotations

from fastapi import APIRouter

from app.matching.engine import get_engine
from app.schemas import ScreenRequest

router = APIRouter(prefix="/match", tags=["matching"])


@router.post("/screen")
def screen(body: ScreenRequest) -> dict:
    """
    Rank a pool of resume texts against one job description.

    Hard filters (minimum experience, required education) run before
    scoring; the reply lists who was ranked, who fell below the threshold,
    and who was excluded and why.
    """
    result = get_engine().screen(
        body.candidates,
        body.job_description,
        similarity_threshold=body.similarity_threshold,
        min_experience_years=body.min_experience_years,
        required_education=body.required_education,
    )
    return {"backend": get_engine().backend_name, **result.as_dict()}
