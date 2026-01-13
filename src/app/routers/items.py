from fastapi import APIRouter, Depends, HTTPException
from typing import List

from app.dependencies import get_token_header

router = APIRouter(
    prefix="/items",
    tags=["items"],
    dependencies=[Depends(get_token_header)],
    responses={404: {"description": "Not found"}},
)

fake_items_db = {"plumbus": {"name": "Plumbus"}, "gun": {"name": "Portal Gun"}}


@router.get("/", response_model=List[dict])
async def read_items():
    return [{"name": item["name"]} for item in fake_items_db.values()]


@router.get("/{item_id}")
async def read_item(item_id: str):
    if item_id not in fake_items_db:
        raise HTTPException(status_code=404, detail="Item not found")
    return fake_items_db[item_id]


@router.post("/")
async def create_item(item: dict):
    item_id = f"item_{len(fake_items_db) + 1}"
    fake_items_db[item_id] = item
    return {"item_id": item_id, "item": item}