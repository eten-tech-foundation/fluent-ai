import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status

from app.dependencies import get_repeated_words_service, require_api_key
from app.logging.utils import get_logger
from app.models.api_key import ApiKey
from app.schemas.greek_room import RepeatedWordsRequest, RepeatedWordsResult
from app.schemas.tool_job import ToolJobResponse
from app.services.greek_room.repeated_words import RepeatedWordsService

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    "/repeated-words",
    response_model=ToolJobResponse[RepeatedWordsResult],
    status_code=status.HTTP_200_OK,
    summary="Run the greek-room repeated-words check",
)
async def check_repeated_words(
    payload: RepeatedWordsRequest,
    service: RepeatedWordsService = Depends(get_repeated_words_service),
    _: ApiKey = Depends(require_api_key),
) -> ToolJobResponse[RepeatedWordsResult]:
    """Synchronous execution of the greek-room repeated-words check.

    The response uses the generic ToolJobResponse envelope with
    status="completed" and the result inline, so callers can safely
    inspect `status` before reading `result` and remain forward-compatible
    if the same URL is later moved behind an asynchronous job queue.
    """
    created_at = datetime.now(timezone.utc)
    logger.debug(
        "repeated-words check requested",
        lang_code=payload.lang_code,
        project_id=payload.project_id,
        verse_count=len(payload.verses),
    )
    result = await service.execute(payload)
    return ToolJobResponse[RepeatedWordsResult](
        job_id=str(uuid.uuid4()),
        tool=service.name,
        status="completed",
        result=result,
        created_at=created_at,
        completed_at=datetime.now(timezone.utc),
    )
