# api/v1/endpoints/ — one module per domain.
#
# Each module defines a single `router = APIRouter()` and attaches route
# handler functions to it. Handlers must:
#   1. Validate the request (FastAPI + Pydantic do this automatically).
#   2. Call exactly one service function.
#   3. Return a Pydantic schema instance.
#
# No DB queries. No business logic. No raw SQL.
#
# Active endpoint modules:
#   api_keys.py   — CRUD for API keys (admin writes, key-holder reads)
#
# Pending migration from app/routers/:
#   projects.py   — list and retrieve projects (read-only, ai_user)
