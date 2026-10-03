from typing import Any, Protocol, Self
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.events import record_event
from app.models import Setting
from app.net.ipplan import IpRange
from app.netconfig import load_netconfig
from app.providers.base import CurrentEntry, DnsQuery, Policy, ProviderError, Reservation
from app.providers.pihole.client import PiholeError
from app.providers.pihole.codec import parse, render
from app.providers.pihole.dns import normalize

KIND = "pihole"
# Never BLOCKED: a blocked device simply has no dhcp-host line and lands in the quarantine pool.
POLICIES = frozenset({Policy.FULL, Policy.LAN_ONLY, Policy.GUEST})
# Janus' own line in misc.dnsmasq_lines, recognised by this prefix (no comment marker: ruling R28).
GUEST_RANGE_PREFIX = "dhcp-range=tag:guest,"
GUEST_RANGE_ERROR_KEY = f"provider.{KIND}.guest_range_error"   # last reported failure, so it is reported once
# A dnsmasq lease time; nothing else may reach the dhcp-host and dhcp-range lines (no ',' or newline).
LEASE_PATTERN = r"^(\d+[smhdw]?|infinite)$"
DISK_AFTER_S = 24 * 3600   # Pi-hole keeps the last 24 h in memory; older queries need the on-disk database


class PiholeConfig(BaseModel):
    url: str
    password: str = ""
    lease: str = Field("24h", pattern=LEASE_PATTERN)


class PiholeApi(Protocol):
    def __enter__(self) -> Any: ...
    def __exit__(self, *exc_info: object) -> Any: ...
    def list_hosts(self) -> list[str]: ...
    def add_host(self, line: str) -> None: ...
    def remove_host(self, line: str) -> None: ...
    def revoke_lease(self, ip: str) -> None: ...
    def get_config(self, path: str) -> dict[str, Any]: ...
    def patch_config(self, config: dict[str, Any]) -> None: ...
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

    def after_sync(self, db: Session) -> None:
        """Keep the guest dhcp-range in step with the guest pool. Pi-hole refuses the write for an app password
        until the cutover turns on app_sudo: that is a sync failure to report (once per distinct reason), not a
        crash."""
        try:
            self.ensure_guest_range(load_netconfig(db).guest_pool(), self.config.lease)
        except ProviderError as exc:
            if not exc.rejected:
                raise
            reason = "guest range needs app_sudo (run the cutover)" if exc.status == 403 else f"guest range: {exc}"
            last = db.get(Setting, GUEST_RANGE_ERROR_KEY)
            if last is None or last.value != reason:
                db.merge(Setting(key=GUEST_RANGE_ERROR_KEY, value=reason))
                record_event(db, "sync.failed", None, {"failed": [reason]})
            return
        last = db.get(Setting, GUEST_RANGE_ERROR_KEY)
        if last is not None:
            db.delete(last)
            db.flush()

    def ensure_guest_range(self, pool: IpRange | None, lease: str) -> None:
        write_guest_range(self.client, pool, lease)

    # LeaseControl
    def force_renew(self, mac: str, ip: str | None) -> None:
        if ip:
            self.client.revoke_lease(ip)

    # DhcpServerState
    def dhcp_server_active(self) -> bool:
        try:
            active = self.client.get_config("dhcp")["dhcp"]["active"]
        except (KeyError, TypeError) as exc:
            raise PiholeError("GET /api/config/dhcp: unexpected reply") from exc
        if not isinstance(active, bool):
            raise PiholeError("GET /api/config/dhcp: unexpected reply, dhcp.active is not a boolean")
        return active

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


def guest_range_line(pool: IpRange, lease: str) -> str:
    return f"{GUEST_RANGE_PREFIX}{pool.start},{pool.end},{lease}"


def guest_range_lines(lines: list[str]) -> list[str]:
    """Janus' guest range lines among misc.dnsmasq_lines, stripped."""
    return [line.strip() for line in lines if line.strip().startswith(GUEST_RANGE_PREFIX)]


def write_guest_range(client: PiholeApi, pool: IpRange | None, lease: str) -> None:
    """Write Janus' `dhcp-range=tag:guest,...` line to misc.dnsmasq_lines (or drop it without a pool). Lines
    without the prefix are never touched; nothing is written when the line is already right."""
    try:
        lines = client.get_config("misc/dnsmasq_lines")["misc"]["dnsmasq_lines"]
    except (KeyError, TypeError) as exc:
        raise PiholeError("GET /api/config/misc/dnsmasq_lines: unexpected reply") from exc
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        raise PiholeError("GET /api/config/misc/dnsmasq_lines: unexpected reply, not a list of lines")
    wanted = [guest_range_line(pool, lease)] if pool is not None else []
    if guest_range_lines(lines) == wanted:
        return
    others = [line for line in lines if not line.strip().startswith(GUEST_RANGE_PREFIX)]
    client.patch_config({"misc": {"dnsmasq_lines": others + wanted}})
