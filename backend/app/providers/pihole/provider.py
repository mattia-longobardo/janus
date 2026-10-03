from typing import Any, Protocol, Self
from urllib.parse import urlparse

from pydantic import BaseModel

from app.providers.base import CurrentEntry, DnsQuery, Policy, Reservation
from app.providers.pihole.codec import parse, render
from app.providers.pihole.dns import normalize

KIND = "pihole"
# Never BLOCKED: a blocked device simply has no dhcp-host line and lands in the quarantine pool.
POLICIES = frozenset({Policy.FULL, Policy.LAN_ONLY})
DISK_AFTER_S = 24 * 3600   # Pi-hole keeps the last 24 h in memory; older queries need the on-disk database


class PiholeConfig(BaseModel):
    url: str
    password: str = ""
    lease: str = "24h"


class PiholeApi(Protocol):
    def __enter__(self) -> Any: ...
    def __exit__(self, *exc_info: object) -> Any: ...
    def list_hosts(self) -> list[str]: ...
    def add_host(self, line: str) -> None: ...
    def remove_host(self, line: str) -> None: ...
    def revoke_lease(self, ip: str) -> None: ...
    def list_queries(self, client_ip: str, since: int, until: int, length: int = 5000,
                     disk: bool = False) -> tuple[list[dict[str, Any]], int]: ...


class PiholeProvider:
    def __init__(self, client: PiholeApi, config: PiholeConfig) -> None:
        self.client = client
        self.config = config

    def __enter__(self) -> Self:
        self.client.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.client.__exit__(*exc_info)

    # ReservationStore
    def list_reservations(self) -> list[CurrentEntry]:
        return [parse(raw, self.config.lease) for raw in self.client.list_hosts()]

    def add_reservation(self, reservation: Reservation) -> None:
        self.client.add_host(render(reservation, self.config.lease))

    def remove_reservation(self, entry: CurrentEntry) -> None:
        self.client.remove_host(entry.key)

    def describe(self, reservation: Reservation) -> str:
        return render(reservation, self.config.lease)

    # LeaseControl
    def force_renew(self, mac: str, ip: str | None) -> None:
        if ip:
            self.client.revoke_lease(ip)

    # DnsQueryLog
    def query_log(self, client_ip: str, since: int, until: int, limit: int = 5000) -> tuple[list[DnsQuery], int]:
        raw, total = self.client.list_queries(client_ip, since, until, limit, disk=until - since > DISK_AFTER_S)
        return [normalize(q) for q in raw], total

    # DnsProbe
    def probe_host(self) -> str | None:
        return urlparse(self.config.url).hostname

    # HealthCheck
    def check(self) -> str:
        return f"{len(self.client.list_hosts())} reservations"
