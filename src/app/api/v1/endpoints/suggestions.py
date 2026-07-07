from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MAX_SUGGESTION_BATCH_SIZE
from app.dependencies import get_db, require_api_key
from app.errors.exceptions import ValidationException
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
    if len(requests) > MAX_SUGGESTION_BATCH_SIZE:
        raise ValidationException(
            message=(
                f"Batch of {len(requests)} requests exceeds the maximum of "
                f"{MAX_SUGGESTION_BATCH_SIZE} per call."
            ),
            details={"count": len(requests), "max": MAX_SUGGESTION_BATCH_SIZE},
        )
    return await enqueue_suggestion_jobs(db, requests)
