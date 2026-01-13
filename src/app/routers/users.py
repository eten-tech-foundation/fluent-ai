from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Dict
from pydantic import BaseModel

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={404: {"description": "Not found"}},
)


class User(BaseModel):
    username: str
    email: str
    full_name: str | None = None
    disabled: bool | None = False


class UserInDB(User):
    hashed_password: str


fake_users_db: Dict[str, UserInDB] = {
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


@router.get("/", response_model=List[User])
async def read_users():
    return [
        User(
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            disabled=user.disabled,
        )
        for user in fake_users_db.values()
    ]


@router.get("/{username}", response_model=User)
async def read_user(username: str):
    user = fake_users_db.get(username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return User(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        disabled=user.disabled,
    )


@router.post("/", response_model=User)
async def create_user(user: User):
    if user.username in fake_users_db:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )
    
    user_in_db = UserInDB(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        disabled=user.disabled,
        hashed_password="fakehashedpassword",
    )
    fake_users_db[user.username] = user_in_db
    return user