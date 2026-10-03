"""What the rest of Janus asks about the configured providers, without knowing which ones they are."""
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from ipaddress import AddressValueError, IPv4Address
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models import Setting
from app.providers import registry
from app.providers.base import Capability, DnsProbe, Policy, ProviderError, Role, role_capabilities
from app.providers.config import RoleConfig, load_role

log = logging.getLogger(__name__)
ProviderFactory = Callable[[], AbstractContextManager[Any]]
DhcpRef = tuple[str, frozenset[Policy], ProviderFactory]   # kind, supported policies, opens the provider
DnsLogRef = tuple[str, ProviderFactory]                     # kind, opens a provider implementing DnsQueryLog
DHCP_IDENTITY_KEY = "dhcp.identity"


def provider_factory(db: Session, role: Role) -> ProviderFactory | None:
    rc = load_role(db, role)
    if rc is None:
        return None
    return lambda: rc.spec.open(rc.config)


def label(kind: str) -> str:
    try:
        return registry.get_spec(kind).label
    except registry.UnknownProvider:
        return kind


def _with(db: Session, role: Role, cap: Capability) -> RoleConfig | None:
    rc = load_role(db, role)
    return rc if rc is not None and cap in role_capabilities(rc.spec, role) else None


def reservation_provider(db: Session) -> DhcpRef | None:
    """The DHCP provider Janus writes reservations to, or None when no provider holding DHCP can take them."""
    rc = _with(db, Role.DHCP, Capability.RESERVATIONS)
    if rc is None:
        return None
    return rc.kind, rc.spec.policies, lambda: rc.spec.open(rc.config)


def dhcp_identity(db: Session, kind: str) -> str:
    """Which box holds DHCP: the provider kind plus its URL when it has one."""
    rc = load_role(db, Role.DHCP)
    url = getattr(rc.config, "url", None) if rc is not None and rc.kind == kind else None
    return f"{kind} {url}" if url else kind


def record_dhcp_identity(db: Session, kind: str) -> bool:
    """Remember which box holds DHCP; True when it differs from the one recorded before (the first is only kept).
    The worker forces dry-run on a change; switching to apply records the box the admin reviewed."""
    identity = dhcp_identity(db, kind)
    seen = db.get(Setting, DHCP_IDENTITY_KEY)
    if seen is not None and seen.value == identity:
        return False
    db.merge(Setting(key=DHCP_IDENTITY_KEY, value=identity))
    return seen is not None


def dns_query_log(db: Session) -> DnsLogRef | None:
    rc = _with(db, Role.DNS, Capability.DNS_QUERY_LOG)
    if rc is None:
        return None
    return rc.kind, lambda: rc.spec.open(rc.config)


def dns_probe_host(db: Session) -> str | None:
    """Host the sentinel probes with DNS queries, or None when the DNS provider cannot be probed."""
    rc = _with(db, Role.DNS, Capability.DNS_PROBE)
    if rc is None:
        return None
    try:
        with rc.spec.open(rc.config) as provider:
            return provider.probe_host() if isinstance(provider, DnsProbe) else None
    except ProviderError:
        log.exception("could not read the DNS probe host from %s", rc.spec.label)
        return None


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
