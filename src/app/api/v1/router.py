# api/v1/router.py — aggregates all v1 endpoint routers.
#
# This is the only file main.py needs to import. It collects every endpoint
# module and includes their routers with the appropriate prefix/tags.
#
# When this file is active, main.py should look like:
#   from app.api.v1.router import router as api_v1_router
#   app.include_router(api_v1_router, prefix="/api/v1")
#
# Example contents when endpoints are migrated here:
#
#   from fastapi import APIRouter
#   from app.api.v1.endpoints import projects, api_keys
#
#   router = APIRouter()
#   router.include_router(projects.router, prefix="/projects", tags=["projects"])
#   router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
