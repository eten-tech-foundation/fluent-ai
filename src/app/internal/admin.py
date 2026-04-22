from fastapi import APIRouter, Depends

from app.models.api_key import ApiKey
from app.security.auth import require_admin

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    responses={404: {"description": "Not found"}},
)


@router.get("/stats", dependencies=[Depends(require_admin)])
async def get_admin_stats():
    """Get administrative statistics"""
    return {
        "total_items": 2,
        "server_uptime": "2 days, 3 hours",
    }


@router.get("/health", dependencies=[Depends(require_admin)])
async def admin_health_check():
    """Admin health check with more details"""
    return {
        "status": "healthy",
        "database": "connected",
        "cache": "connected",
        "version": "0.1.0",
    }