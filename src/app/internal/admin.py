from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    responses={404: {"description": "Not found"}},
)


@router.get("/stats")
async def get_admin_stats():
    """Get administrative statistics"""
    return {
        "total_users": 2,
        "total_items": 2,
        "active_sessions": 0,
        "server_uptime": "2 days, 3 hours"
    }


@router.get("/health")
async def admin_health_check():
    """Admin health check with more details"""
    return {
        "status": "healthy",
        "database": "connected",
        "cache": "connected",
        "version": "0.1.0"
    }