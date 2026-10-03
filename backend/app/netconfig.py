import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, fields, replace
from ipaddress import AddressValueError, IPv4Address, IPv4Network, NetmaskValueError
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Group, Setting
from app.net.ipplan import IpRange, NetworkPlan

NETWORK_KEY = "network.config"
INTERFACE = re.compile(r"^[A-Za-z0-9_.:-]{1,32}$")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
RESTART_FIELDS = ("subnet", "gateway", "quarantine_start", "quarantine_end", "sentinel_interface", "sweep_interval_s")


@dataclass(frozen=True)
class NetConfig:
    subnet: str
    gateway: str
    quarantine_start: str
    quarantine_end: str
    sentinel_interface: str
    sweep_interval_s: int
    scan_window_start: str
    scan_window_end: str

    def plan(self) -> NetworkPlan:
        return NetworkPlan.from_settings(self)


FIELDS = tuple(f.name for f in fields(NetConfig))


class NetConfigError(ValueError):
    pass


def env_defaults() -> NetConfig:
    return NetConfig(**{name: getattr(settings, name) for name in FIELDS})


def stored_overrides(db: Session) -> dict[str, Any]:
    row = db.get(Setting, NETWORK_KEY)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    return {k: v for k, v in value.items() if k in FIELDS and v is not None}


def load_netconfig(db: Session) -> NetConfig:
    base = env_defaults()
    overrides = stored_overrides(db)
    if not overrides:
        return base
    try:
        return validate(replace(base, **overrides), _group_ranges(db))
    except (NetConfigError, TypeError):
        return base


def load_with(session_factory: Callable[[], AbstractContextManager[Session]]) -> NetConfig:
    with session_factory() as db:
        return load_netconfig(db)


def _group_ranges(db: Session) -> list[tuple[str, IpRange]]:
    ranges = []
    for group in db.scalars(select(Group)):
        try:
            ranges.append((group.name, group.ip_range()))
        except ValueError:
            continue
    return ranges


def _address(value: Any, label: str) -> IPv4Address:
    try:
        return IPv4Address(str(value).strip())
    except (AddressValueError, ValueError) as exc:
        raise NetConfigError(f"{label}: {value!r} is not an IPv4 address") from exc


def validate(cfg: NetConfig, group_ranges: list[tuple[str, IpRange]]) -> NetConfig:
    try:
        network = IPv4Network(str(cfg.subnet).strip(), strict=False)
    except (AddressValueError, NetmaskValueError, ValueError) as exc:
        raise NetConfigError(f"subnet: {cfg.subnet!r} is not an IPv4 network like 192.168.1.0/24") from exc
    if network.prefixlen < 16 or network.prefixlen > 30:
        raise NetConfigError("subnet: use a prefix between /16 and /30")
    gateway = _address(cfg.gateway, "gateway")
    if gateway not in network:
        raise NetConfigError(f"gateway: {gateway} is outside {network}")
    q_start = _address(cfg.quarantine_start, "quarantine_start")
    q_end = _address(cfg.quarantine_end, "quarantine_end")
    if q_start not in network or q_end not in network:
        raise NetConfigError(f"quarantine pool must be inside {network}")
    if q_start > q_end:
        raise NetConfigError("quarantine pool: start is after end")
    pool = IpRange(q_start, q_end)
    if gateway in pool:
        raise NetConfigError("quarantine pool must not contain the gateway")
    for name, rng in group_ranges:
        if rng.start not in network or rng.end not in network:
            raise NetConfigError(f"subnet: group {name} ({rng}) would fall outside {network}")
        if rng.overlaps(pool):
            raise NetConfigError(f"quarantine pool overlaps group {name} ({rng})")
    if not INTERFACE.match(str(cfg.sentinel_interface)):
        raise NetConfigError("sentinel_interface: letters, digits and . _ : - only (max 32)")
    try:
        sweep = int(cfg.sweep_interval_s)
    except (TypeError, ValueError) as exc:
        raise NetConfigError("sweep_interval_s: must be a whole number of seconds") from exc
    if not 10 <= sweep <= 3600:
        raise NetConfigError("sweep_interval_s: must be between 10 and 3600 seconds")
    for label, value in (("scan_window_start", cfg.scan_window_start), ("scan_window_end", cfg.scan_window_end)):
        if not HHMM.match(str(value)):
            raise NetConfigError(f"{label}: use HH:MM")
    return NetConfig(
        subnet=str(network), gateway=str(gateway), quarantine_start=str(q_start), quarantine_end=str(q_end),
        sentinel_interface=str(cfg.sentinel_interface),
        sweep_interval_s=sweep, scan_window_start=str(cfg.scan_window_start), scan_window_end=str(cfg.scan_window_end),
    )


def update_netconfig(db: Session, patch: Mapping[str, Any]) -> tuple[NetConfig, dict[str, list[Any]]]:
    unknown = set(patch) - set(FIELDS)
    if unknown:
        raise NetConfigError(f"unknown network fields: {', '.join(sorted(unknown))}")
    before = load_netconfig(db)
    defaults = env_defaults()
    overrides = stored_overrides(db)
    for key, value in patch.items():
        if value is None:
            overrides.pop(key, None)
        else:
            overrides[key] = value
    candidate = validate(replace(defaults, **overrides), _group_ranges(db))
    stored = {k: getattr(candidate, k) for k in overrides if getattr(candidate, k) != getattr(defaults, k)}
    db.merge(Setting(key=NETWORK_KEY, value=stored))
    old, new = asdict(before), asdict(candidate)
    changes = {k: [old[k], new[k]] for k in FIELDS if old[k] != new[k]}
    return candidate, changes


def sources(db: Session) -> dict[str, str]:
    overrides = stored_overrides(db)
    return {name: "custom" if name in overrides else "env" for name in FIELDS}


def restart_needed(started: NetConfig, current: NetConfig) -> list[str]:
    return [name for name in RESTART_FIELDS if getattr(started, name) != getattr(current, name)]
