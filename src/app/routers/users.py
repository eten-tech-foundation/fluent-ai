"""
routers/users.py — HTTP route handlers for the users domain.

Note: This router currently uses an in-memory fake store.
      Real database wiring is tracked in a separate ticket.
"""

from fastapi import APIRouter, status

from app.errors.exceptions import ConflictException, NotFoundException
from app.errors.logging import get_logger
from app.schemas.users import User, UserCreate, UserInDB

logger = get_logger(__name__)

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={404: {"description": "Not found"}},
)


# --------------------------------------------------------------------------- #
# In-memory store (placeholder until DB wiring is complete)
# --------------------------------------------------------------------------- #

fake_users_db: dict[str, UserInDB] = {
    "johndoe": UserInDB(
        username="johndoe",
        email="john@example.com",
        full_name="John Doe",
        hashed_password="fakehashedsecret",
    ),
    "alice": UserInDB(
        username="alice",
        email="alice@example.com",
        full_name="Alice Smith",
        hashed_password="fakehashedsecret2",
    ),
}


# --------------------------------------------------------------------------- #
# Route handlers
# --------------------------------------------------------------------------- #


@router.get("/", response_model=list[User])
async def read_users() -> list[User]:
    return [
        User(
            username=u.username,
            email=u.email,
            full_name=u.full_name,
            disabled=u.disabled,
        )
        for u in fake_users_db.values()
    ]


@router.get("/{username}", response_model=User)
async def read_user(username: str) -> User:
    user = fake_users_db.get(username)
    if user is None:
        raise NotFoundException(
            message=f"User '{username}' not found.",
            details={"username": username},
        )
    return User(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        disabled=user.disabled,
    )


@router.post("/", response_model=User, status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate) -> User:
    if user.username in fake_users_db:
        raise ConflictException(
            message=f"Username '{user.username}' is already registered.",
            details={"username": user.username},
        )

    user_in_db = UserInDB(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        disabled=user.disabled,
        hashed_password="fakehashedpassword",
    )
    fake_users_db[user.username] = user_in_db

    logger.info("User created: %s", user.username)

    return User(
        username=user_in_db.username,
        email=user_in_db.email,
        full_name=user_in_db.full_name,
        disabled=user_in_db.disabled,
    )
