# core/exceptions.py — custom exception types and handlers.
#
# Define application-specific exceptions here and register handlers on the
# FastAPI app in main.py via app.add_exception_handler(...).
#
# Why this matters: centralizing exception handling prevents routers from
# raising bare HTTPException with inline status codes and messages scattered
# across the codebase. Instead, raise typed exceptions here; the handler
# converts them to the correct HTTP response.
#
# Example contents when this file is implemented:
#
#   from fastapi import Request
#   from fastapi.responses import JSONResponse
#
#   class NotFoundError(Exception):
#       def __init__(self, resource: str, id: int | str):
#           self.resource = resource
#           self.id = id
#
#   class PermissionDeniedError(Exception):
#       pass
#
#   async def not_found_handler(request: Request, exc: NotFoundError):
#       return JSONResponse(status_code=404, content={"detail": f"{exc.resource} {exc.id} not found"})
#
#   async def permission_denied_handler(request: Request, exc: PermissionDeniedError):
#       return JSONResponse(status_code=403, content={"detail": "Permission denied"})
#
# Registration in main.py:
#   from app.core.exceptions import NotFoundError, not_found_handler
#   app.add_exception_handler(NotFoundError, not_found_handler)
