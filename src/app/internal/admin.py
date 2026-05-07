from fastapi import APIRouter, Depends

from app.dependencies import GoogleGeminiDep
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
        "version": "0.1.0"
    }


@router.get("/ai-test")
async def test_ai_connectivity(
    gemini_client: GoogleGeminiDep,
    prompt: str = "Say hello in exactly 5 words.",
):
    """
    Live test of the Google Gemini integration.
    Makes a real API request to verify credentials.
    """
    try:
        response_text = await gemini_client.generate_content(prompt)
        return {
            "status": "success",
            "message": "API key is valid and working.",
            "model": gemini_client._model_name,
            "prompt": prompt,
            "response": response_text,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": "API request failed.",
            "error": str(e)
        }