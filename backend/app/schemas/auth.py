import uuid
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["scientist", "lab_analyst", "senior_analyst", "admin"]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    full_name: str
    role: Role
    department: str | None = None
    model_config = {"from_attributes": True}


class MeOut(BaseModel):
    user: UserOut
    permissions: list[str]


class LoginOut(MeOut):
    token: str


class DemoUserCard(BaseModel):
    username: str
    full_name: str
    role: Role
    department: str | None = None


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(min_length=1, max_length=120)
    role: Role
    department: str | None = None


class RoleUpdate(BaseModel):
    role: Role
