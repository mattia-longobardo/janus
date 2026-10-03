"""What the rest of Janus asks about the configured providers, without knowing which ones they are."""
from collections.abc import Callable
from contextlib import AbstractContextManager
from ipaddress import AddressValueError, IPv4Address
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models import Setting
from app.providers.base import Capability, Policy, Role, role_capabilities
from app.providers.config import RoleConfig, load_role


def provider_factory(db: Session, role: Role) -> Callable[[], AbstractContextManager[Any]] | None:
    rc = load_role(db, role)
    if rc is None:
        return None
    return lambda: rc.spec.open(rc.config)


def has_capability(db: Session, role: Role, cap: Capability) -> bool:
    rc = load_role(db, role)
    return rc is not None and cap in role_capabilities(rc.spec, role)


def policies(db: Session) -> frozenset[Policy]:
    rc = load_role(db, Role.DHCP)
    return rc.spec.policies if rc is not None else frozenset()


def role_ref(db: Session, role: Role) -> dict[str, Any] | None:
    rc = load_role(db, role)
    if rc is None:
        return None
    down = db.get(Setting, f"{role}.down_since")
    ref: dict[str, Any] = {
        "kind": rc.kind,
        "label": rc.spec.label,
        "capabilities": sorted(role_capabilities(rc.spec, role)),
        "shared": rc.shared,
        "down_since": down.value if down is not None else None,
    }
    if role is Role.DHCP:
        ref["policies"] = sorted(rc.spec.policies)
    return ref


def providers_feature(db: Session) -> dict[str, Any]:
    return {role.value: role_ref(db, role) for role in (Role.DHCP, Role.DNS)}


def _host_ip(rc: RoleConfig) -> str | None:
    url = getattr(rc.config, "url", None)
    if not url:
        return None
    try:
        return str(IPv4Address(urlparse(str(url)).hostname or ""))
    except (AddressValueError, ValueError):
        return None


def infrastructure_ips(db: Session) -> set[str]:
    """IPv4 hosts of the active providers: compaction and IP planning must never hand them to a device."""
    ips = {_host_ip(rc) for role in Role if (rc := load_role(db, role)) is not None}
    return {ip for ip in ips if ip}
