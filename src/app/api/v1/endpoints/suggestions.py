from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_api_key
from app.schemas.suggestions import SuggestionTriggerRequest, SuggestionTriggerResponse
from app.services.suggestions import enqueue_suggestion_jobs

router = APIRouter()


@router.post(
    "",
    response_model=SuggestionTriggerResponse,
    summary="Trigger AI suggestion jobs",
    dependencies=[Depends(require_api_key)],
)
async def trigger_suggestions(
    requests: list[SuggestionTriggerRequest],
    db: AsyncSession = Depends(get_db),
) -> SuggestionTriggerResponse:
    """
    Enqueue AI translation suggestion jobs in the generic jobs table.
    """
    return await enqueue_suggestion_jobs(db, requests)
