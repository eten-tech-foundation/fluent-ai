from fastapi import FastAPI

from app.api.v1.router import router as api_v1_router
from app.config import get_settings
from app.routers import projects

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="AI Services for the Fluent Ecosystem",
    version=settings.app_version,
    debug=settings.debug,
)

# Include routers
app.include_router(projects.router, tags=["projects"])
app.include_router(api_v1_router)

# GET /docs provides interactive API documentation
# GET /redoc provides alternative interactive API documentation
# GET /openapi.json provides OpenAPI schema

@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": settings.app_version,
        "environment": settings.environment,
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

