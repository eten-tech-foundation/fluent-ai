from fastapi import APIRouter

from app.api.v1.endpoints import api_keys, greek_room, suggestions, translations

router = APIRouter()
router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
router.include_router(
    greek_room.router,
    prefix="/tools/greek-room",
    tags=["tools:greek-room"],
)
router.include_router(suggestions.router, prefix="/suggestions", tags=["suggestions"])
router.include_router(
    translations.router, prefix="/translations", tags=["translations"]
)
