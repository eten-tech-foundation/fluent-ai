from fastapi import APIRouter

from app.api.v1.endpoints import api_keys

router = APIRouter()
router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
