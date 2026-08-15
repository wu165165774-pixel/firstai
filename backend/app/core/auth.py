from __future__ import annotations

import json
import secrets

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config.settings import settings


bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="NovelForge static bearer token configured by the operator.",
)


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: str | None
    roles: tuple[str, ...] = ()
    authenticated: bool = False

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


def configured_principals() -> list[tuple[str, AuthPrincipal]]:
    if not settings.auth_enabled:
        return []

    try:
        payload = json.loads(settings.auth_tokens_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("AUTH_TOKENS_JSON must be a valid JSON object.") from exc

    if not isinstance(payload, dict) or not payload:
        raise ValueError(
            "AUTH_TOKENS_JSON must contain at least one token when auth is enabled."
        )

    result: list[tuple[str, AuthPrincipal]] = []
    for token, raw_principal in payload.items():
        token = str(token or "")
        if len(token) < 16 or len(token) > 512:
            raise ValueError("Authentication tokens must contain 16 to 512 characters.")
        if not isinstance(raw_principal, dict):
            raise ValueError("Each authentication token must map to an object.")

        user_id = str(raw_principal.get("user_id") or "").strip()
        if not user_id or len(user_id) > 128:
            raise ValueError("Each authentication principal requires a valid user_id.")

        raw_roles = raw_principal.get("roles", ["user"])
        if not isinstance(raw_roles, list):
            raise ValueError("Authentication principal roles must be a JSON array.")
        roles = tuple(dict.fromkeys(str(role).strip() for role in raw_roles if str(role).strip()))
        if not roles or any(len(role) > 64 for role in roles):
            raise ValueError("Authentication principal roles are invalid.")

        result.append(
            (
                token,
                AuthPrincipal(
                    user_id=user_id,
                    roles=roles,
                    authenticated=True,
                ),
            )
        )
    return result


def validate_auth_configuration() -> None:
    configured_principals()


def _unauthorized(detail: str = "Bearer authentication required.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def authenticate_request(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> AuthPrincipal:
    if not settings.auth_enabled:
        principal = AuthPrincipal(user_id=None, roles=("anonymous",))
        request.state.auth_principal = principal
        return principal

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    try:
        principals = configured_principals()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured safely.",
        ) from exc

    principal: AuthPrincipal | None = None
    for configured_token, candidate in principals:
        if secrets.compare_digest(credentials.credentials, configured_token):
            principal = candidate

    if principal is None:
        raise _unauthorized("Invalid bearer token.")

    request.state.auth_principal = principal
    return principal


def _collect_named_values(value: Any, name: str) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == name and item is not None:
                normalized = str(item).strip()
                if normalized:
                    result.add(normalized)
            result.update(_collect_named_values(item, name))
    elif isinstance(value, list):
        for item in value:
            result.update(_collect_named_values(item, name))
    return result


async def _json_payload(request: Request) -> Any:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if "application/json" not in request.headers.get("content-type", ""):
        return None
    try:
        return await request.json()
    except Exception:
        return None


def _hide_resource() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Resource not found.",
    )


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


async def _authorize_novels(principal: AuthPrincipal, novel_ids: set[str]) -> None:
    if not novel_ids:
        return
    from app.api.v1.novels import service as novel_service
    from app.novels.storage import NovelProjectNotFoundError

    for novel_id in novel_ids:
        try:
            project = novel_service.get_project(novel_id)
        except NovelProjectNotFoundError:
            continue
        if project.user_id != principal.user_id:
            raise _hide_resource()


def _authorize_workflow_run(principal: AuthPrincipal, run_id: str | None) -> None:
    if not run_id:
        return
    from app.workflows.storage import WorkflowRunStorage

    try:
        run = WorkflowRunStorage().get_run(run_id)
    except KeyError:
        return
    owner = str(
        run.get("user_id")
        or (run.get("request") or {}).get("user_id")
        or ""
    ).strip()
    if owner and owner != principal.user_id:
        raise _hide_resource()


async def _authorize_memory(principal: AuthPrincipal, memory_id: str | None) -> None:
    if not memory_id:
        return
    from app.memory.manager import memory_manager

    memory = await memory_manager.storage["sqlite"].get(memory_id)
    if memory is not None and memory.user_id != principal.user_id:
        raise _hide_resource()


def _requires_admin(path: str) -> bool:
    prefixes = (
        "/api/v1/workflows/workers",
        "/api/v1/workflows/queue",
        "/api/v1/workflows/dead-letter",
        "/api/v1/workflows/operations",
        "/api/v1/workflows/metrics",
    )
    return path.startswith(prefixes)


async def authorize_request(
    request: Request,
    principal: AuthPrincipal = Depends(authenticate_request),
) -> AuthPrincipal:
    if not principal.authenticated:
        return principal
    if principal.is_admin:
        return principal

    path = request.url.path
    if _requires_admin(path):
        raise _forbidden("Administrator role required.")

    payload = await _json_payload(request)
    path_values = dict(request.path_params)
    query_values = dict(request.query_params)

    user_ids = _collect_named_values(path_values, "user_id")
    user_ids.update(_collect_named_values(query_values, "user_id"))
    user_ids.update(_collect_named_values(payload, "user_id"))
    if any(user_id != principal.user_id for user_id in user_ids):
        raise _forbidden("Authenticated user does not match the requested user scope.")

    requires_explicit_user = (
        request.method == "GET"
        and path in {
            "/api/v1/novels",
            "/api/v1/workflows/runs",
        }
    ) or (request.method == "POST" and path == "/api/v1/chat")
    if requires_explicit_user and not user_ids:
        raise _forbidden("An explicit authenticated user scope is required.")

    novel_ids = _collect_named_values(path_values, "novel_id")
    novel_ids.update(_collect_named_values(query_values, "novel_id"))
    novel_ids.update(_collect_named_values(payload, "novel_id"))
    await _authorize_novels(principal, novel_ids)

    _authorize_workflow_run(principal, request.path_params.get("run_id"))
    await _authorize_memory(principal, request.path_params.get("memory_id"))
    return principal
