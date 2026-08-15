from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.auth import AuthPrincipal, authenticate_request


router = APIRouter(prefix="/auth")


class AuthIdentity(BaseModel):
    authenticated: bool
    user_id: str | None = None
    roles: list[str] = Field(default_factory=list)


class AuthIdentityResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: AuthIdentity


@router.get("/me", response_model=AuthIdentityResponse)
async def get_authenticated_identity(
    principal: AuthPrincipal = Depends(authenticate_request),
) -> AuthIdentityResponse:
    return AuthIdentityResponse(
        data=AuthIdentity(
            authenticated=principal.authenticated,
            user_id=principal.user_id,
            roles=list(principal.roles),
        )
    )
