"""
routers/items.py — HTTP route handlers for the items domain.
"""

from fastapi import APIRouter, Depends, Query, status

from app.dependencies import get_token_header
from app.errors.exceptions import ConflictException, NotFoundException
from app.errors.logging import get_logger
from app.schemas.items import ItemCreate, ItemResponse

logger = get_logger(__name__)

router = APIRouter(
    prefix="/items",
    tags=["items"],
    dependencies=[Depends(get_token_header)],
    responses={404: {"description": "Not found"}},
)

# --------------------------------------------------------------------------- #
# In-memory store (placeholder until DB wiring is complete)
# --------------------------------------------------------------------------- #

fake_items_db: dict[str, dict] = {
    "plumbus": {"name": "Plumbus", "description": "Everyone has one."},
    "gun": {"name": "Portal Gun", "description": "Opens interdimensional portals."},
}


# --------------------------------------------------------------------------- #
# Route handlers
# --------------------------------------------------------------------------- #


@router.get("/", response_model=list[ItemResponse])
async def read_items(
    limit: int = Query(default=50, ge=1, le=200, description="Max items to return."),
    offset: int = Query(default=0, ge=0, description="Number of items to skip."),
) -> list[ItemResponse]:
    items = list(fake_items_db.items())
    page = items[offset : offset + limit]
    return [
        ItemResponse(
            item_id=item_id,
            name=data["name"],
            description=data.get("description"),
        )
        for item_id, data in page
    ]


@router.get("/{item_id}", response_model=ItemResponse)
async def read_item(item_id: str) -> ItemResponse:
    item = fake_items_db.get(item_id)
    if item is None:
        raise NotFoundException(
            message=f"Item '{item_id}' not found.",
            details={"item_id": item_id},
        )
    return ItemResponse(
        item_id=item_id,
        name=item["name"],
        description=item.get("description"),
    )


@router.post("/", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(item: ItemCreate) -> ItemResponse:
    # Generate a slug-style ID from the name.
    item_id = item.name.lower().replace(" ", "_")

    if item_id in fake_items_db:
        raise ConflictException(
            message=f"An item with the name '{item.name}' already exists.",
            details={"item_id": item_id},
        )

    fake_items_db[item_id] = {
        "name": item.name,
        "description": item.description,
    }

    logger.info("Item created: %s", item_id)

    return ItemResponse(
        item_id=item_id,
        name=item.name,
        description=item.description,
    )
