from fastapi import Header, HTTPException, status
from typing import Optional


async def get_token_header(x_token: str = Header(...)):
    if x_token != "fake-super-secret-token":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Token header invalid",
        )


async def get_query_token(token: Optional[str] = None):
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token query parameter required",
        )
    return token