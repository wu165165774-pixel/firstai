from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address, ip_address

from app.config.settings import settings


class DeploymentSecurityError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Deployment security validation failed: {code}")


@dataclass(frozen=True)
class DeploymentSecurityStatus:
    bind_host: str
    loopback_only: bool
    auth_enabled: bool
    debug_enabled: bool
    insecure_override: bool


def validate_deployment_security(
    *,
    bind_host: str | None = None,
    auth_enabled: bool | None = None,
    debug_enabled: bool | None = None,
    allow_insecure_network_exposure: bool | None = None,
) -> DeploymentSecurityStatus:
    normalized_host = str(
        settings.novelforge_bind_host if bind_host is None else bind_host
    ).strip()
    try:
        address = ip_address(normalized_host)
    except ValueError as exc:
        raise DeploymentSecurityError("invalid_bind_host") from exc
    if not isinstance(address, IPv4Address):
        raise DeploymentSecurityError("invalid_bind_host")

    auth = settings.auth_enabled if auth_enabled is None else bool(auth_enabled)
    debug = settings.debug if debug_enabled is None else bool(debug_enabled)
    override = (
        settings.allow_insecure_network_exposure
        if allow_insecure_network_exposure is None
        else bool(allow_insecure_network_exposure)
    )
    loopback_only = address.is_loopback
    if not loopback_only and not override:
        if not auth or debug:
            raise DeploymentSecurityError("unsafe_network_exposure")

    return DeploymentSecurityStatus(
        bind_host=str(address),
        loopback_only=loopback_only,
        auth_enabled=auth,
        debug_enabled=debug,
        insecure_override=override,
    )
