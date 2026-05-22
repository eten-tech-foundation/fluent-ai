from fastapi import APIRouter

from app.api.v1.endpoints import api_keys, greek_room

router = APIRouter()
router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
router.include_router(
    greek_room.router,
    prefix="/tools/greek-room",
    tags=["tools:greek-room"],
)
