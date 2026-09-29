"""Request/response schemas for the auth API."""
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

Role = Literal["driver", "operator"]


class _EmailMixin(BaseModel):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v


class SignUpIn(_EmailMixin):
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    role: Role = "driver"
    operator_code: Optional[str] = Field(None, max_length=128, description="Invite code, required for role=operator")

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("Password must contain at least one letter and one number")
        return v


class SignInIn(_EmailMixin):
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: Optional[str] = Field(None, description="Only for non-browser clients; browsers use the cookie")


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: Role


class AuthOut(BaseModel):
    user: UserOut
    access_token: str
    token_type: str = "bearer"
    expires_in: int
