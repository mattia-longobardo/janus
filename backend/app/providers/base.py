from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from fastapi import APIRouter
from pydantic import BaseModel


class Role(StrEnum):
    DHCP = "dhcp"
    DNS = "dns"


class Capability(StrEnum):
    RESERVATIONS = "reservations"          # per-MAC reservations with an access policy
    FORCE_RENEW = "force_renew"            # make a device ask for a new lease now
    QUARANTINE = "quarantine"              # unknown devices land in a pool without a gateway
    DHCP_SERVER = "dhcp_server"            # the provider can take over DHCP (cutover/preflight/backup)
    DNS_QUERY_LOG = "dns_query_log"
    DNS_PROBE = "dns_probe"                # the sentinel can probe this DNS server
    CLIENT_INVENTORY = "client_inventory"  # live client list with AP / switch port


class Policy(StrEnum):
    FULL = "full"
    LAN_ONLY = "lan_only"
    GUEST = "guest"
    BLOCKED = "blocked"


@dataclass(frozen=True, order=True)
class Reservation:
    mac: str            # normalized, upper-case, colon-separated (app.net.mac.normalize_mac)
    hostname: str
    ip: str | None = None
    policy: Policy = Policy.FULL


@dataclass(frozen=True)
class CurrentEntry:
    key: str                         # native identifier: raw dhcp-host line, UniFi _id, ...
    display: str                     # what the UI and logs show
    mac: str | None
    ip: str | None
    reservation: Reservation | None  # None: not a reservation Janus can read (unmanaged)
    canonical: bool = True           # False: Janus' entry in an outdated format; rewrite it


@dataclass(frozen=True)
class DnsQuery:
    time: float
    domain: str
    qtype: str
    blocked: bool
    status: str
    reply: str | None
    client_ip: str


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def rejected(self) -> bool:
        """The provider refused this one request (4xx); it is reachable."""
        return self.status is not None and 400 <= self.status < 500


@runtime_checkable
class ReservationStore(Protocol):
    def list_reservations(self) -> list[CurrentEntry]: ...
    def add_reservation(self, reservation: Reservation) -> None: ...
    def remove_reservation(self, entry: CurrentEntry) -> None: ...
    def describe(self, reservation: Reservation) -> str: ...


@runtime_checkable
class LeaseControl(Protocol):
    def force_renew(self, mac: str, ip: str | None) -> None: ...


@runtime_checkable
class DnsQueryLog(Protocol):
    def query_log(self, client_ip: str, since: int, until: int, limit: int = 5000) -> tuple[list[DnsQuery], int]: ...


@runtime_checkable
class DnsProbe(Protocol):
    def probe_host(self) -> str | None: ...


@runtime_checkable
class HealthCheck(Protocol):
    def check(self) -> str: ...   # short human summary; raises ProviderError when unreachable


# Which role a capability belongs to: a provider that holds only the DNS role never exposes DHCP capabilities.
CAPABILITY_ROLE: dict[Capability, Role] = {
    Capability.RESERVATIONS: Role.DHCP,
    Capability.FORCE_RENEW: Role.DHCP,
    Capability.QUARANTINE: Role.DHCP,
    Capability.DHCP_SERVER: Role.DHCP,
    Capability.CLIENT_INVENTORY: Role.DHCP,
    Capability.DNS_QUERY_LOG: Role.DNS,
    Capability.DNS_PROBE: Role.DNS,
}


CAPABILITY_PROTOCOL: dict[Capability, type] = {
    Capability.RESERVATIONS: ReservationStore,
    Capability.FORCE_RENEW: LeaseControl,
    Capability.DNS_QUERY_LOG: DnsQueryLog,
    Capability.DNS_PROBE: DnsProbe,
}


@dataclass(frozen=True)
class ProviderSpec:
    kind: str                                   # == folder name
    label: str
    roles: frozenset[Role]
    capabilities: frozenset[Capability]
    config_model: type[BaseModel]
    open: Callable[[Any], AbstractContextManager[Any]]   # config instance -> provider instance
    provider_class: type | None = None          # checked by the contract test (C7)
    policies: frozenset[Policy] = frozenset()
    secret_fields: frozenset[str] = frozenset()
    env_defaults: Callable[[], dict[str, Any]] = dict
    router: APIRouter | None = None             # mounted at /api/providers/<kind>
    cli: Callable[[Any], None] | None = None    # adds `janus` subcommands to an argparse subparsers object
    description: str = ""
    docs_url: str = ""


def role_capabilities(spec: ProviderSpec, role: Role) -> frozenset[Capability]:
    return frozenset(c for c in spec.capabilities if CAPABILITY_ROLE[c] is role)
