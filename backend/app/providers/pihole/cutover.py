import json
import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, select
from sqlalchemy.orm import Session

from app.enforcement.sync import apply_sync, plan_sync
from app.models import Access, Device
from app.netconfig import NetConfig, load_netconfig
from app.providers.pihole.client import PiholeClient, PiholeError
from app.providers.pihole.provider import (
    GUEST_RANGE_PREFIX,
    KIND,
    POLICIES,
    PiholeConfig,
    PiholeProvider,
    guest_range_line,
)
from app.syncmode import load_sync_mode, set_sync_mode

QUARANTINE_LINES = ("dhcp-option=tag:!known,option:router", "dhcp-option=tag:lanonly,option:router")
BACKUP_MAX_AGE = timedelta(hours=24)
SKIP_TABLES = {"sightings", "alembic_version"}


def backup_dir() -> Path:
    return Path(os.environ.get("JANUS_BACKUP_DIR", "/app/backups"))


class PiholeAdmin(PiholeClient):
    """Pi-hole client with the teleporter call needed for the DHCP cutover backup."""

    def teleporter(self) -> bytes:
        return self._request("GET", "/api/teleporter").content


@dataclass
class Check:
    name: str
    ok: bool | None
    detail: str
    blocking: bool = True


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    plan: dict[str, int] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return all(c.ok for c in self.checks if c.blocking)

    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "checks": [asdict(c) for c in self.checks], "plan": self.plan}


def latest_backup(directory: Path) -> datetime | None:
    stamps = []
    for entry in directory.glob("*/janus.json") if directory.is_dir() else []:
        stamps.append(datetime.fromtimestamp(entry.stat().st_mtime, UTC))
    return max(stamps, default=None)


def _device_checks(db: Session, gateway: str) -> list[Check]:
    approved = [d for d in db.scalars(select(Device).where(Device.access.in_([Access.authorized, Access.lan_only])))
                if gateway not in (d.static_ip, d.last_ip)]
    incomplete = sorted(d.name for d in approved if not d.mac or not d.static_ip)
    ips = Counter(d.static_ip for d in approved if d.static_ip)
    macs = Counter(d.mac.lower() for d in approved if d.mac)
    dupes = sorted([f"IP {ip}" for ip, n in ips.items() if n > 1] + [f"MAC {mac}" for mac, n in macs.items() if n > 1])
    return [
        Check("approved_devices_complete", not incomplete,
              f"{len(approved)} approved devices have a MAC and a static IP" if not incomplete
              else f"missing MAC or static IP: {', '.join(incomplete[:10])}"),
        Check("no_duplicates", not dupes, "no duplicate reservations" if not dupes else ", ".join(dupes[:10])),
    ]


def _range_check(net: NetConfig) -> Check:
    try:
        subnet = IPv4Network(net.subnet, strict=False)
        start, end, gateway = IPv4Address(net.quarantine_start), IPv4Address(net.quarantine_end), IPv4Address(net.gateway)
        ok = start in subnet and end in subnet and start <= end and not (start <= gateway <= end)
    except ValueError:
        ok = False
    return Check("dhcp_range", ok, f"Pi-hole will lease {net.quarantine_start}–{net.quarantine_end} to unknown devices"
                 if ok else "quarantine pool is not a valid range inside the subnet")


def _guest_check(net: NetConfig, lines: list[str], lease: str) -> Check:
    """Not blocking: the cutover writes the guest range itself (apply_sync's after_sync) once it can write."""
    pool = net.guest_pool()
    if pool is None:
        return Check("guest_rules", True, "no guest pool defined", blocking=False)
    wanted = guest_range_line(pool, lease)
    if [line.strip() for line in lines if line.strip().startswith(GUEST_RANGE_PREFIX)] == [wanted]:
        return Check("guest_rules", True, f"guest range present: {wanted}", blocking=False)
    return Check("guest_rules", None, f"the cutover will write the guest range: {wanted}", blocking=False)


def _dhcp_role_check(dhcp_kind: str | None) -> Check:
    if dhcp_kind == KIND:
        return Check("pihole_is_dhcp_provider", True, "Pi-hole holds the DHCP role")
    if dhcp_kind is None:
        return Check("pihole_is_dhcp_provider", False, "no DHCP provider is configured: assign the DHCP role to "
                     "Pi-hole first")
    return Check("pihole_is_dhcp_provider", False, f"the DHCP role belongs to {dhcp_kind}: turning on Pi-hole DHCP "
                 "would put a second DHCP server on the LAN")


def preflight(db: Session, client: PiholeAdmin, cfg: PiholeConfig, *, dhcp_kind: str | None,
              admin: PiholeAdmin | None = None, now: datetime | None = None) -> Report:
    """`dhcp_kind` is the provider that holds the DHCP role: the cutover only makes sense when it is this Pi-hole."""
    now = now or datetime.now(UTC)
    net = load_netconfig(db)
    report = Report(checks=[_dhcp_role_check(dhcp_kind)])
    try:
        dhcp = client.get_config("dhcp")["dhcp"]
        lines = client.get_config("misc/dnsmasq_lines")["misc"]["dnsmasq_lines"]
        app_sudo = bool(client.get_config("webserver/api/app_sudo")["webserver"]["api"]["app_sudo"])
    except (PiholeError, KeyError, ValueError) as exc:
        report.checks.append(Check("pihole_reachable", False, f"Pi-hole API not usable: {exc}"))
        report.checks.extend(_device_checks(db, net.gateway))
        return report
    report.checks.append(Check("pihole_reachable", True, f"Pi-hole API answers at {cfg.url}"))
    dhcp_state = "Pi-hole DHCP is already on" if dhcp.get("active") else "Pi-hole DHCP is off (expected before cutover)"
    report.checks.append(Check("pihole_dhcp", True, dhcp_state, blocking=False))
    if admin is not None:
        try:
            admin.get_config("webserver/api/app_sudo")
            report.checks.append(Check("write_access", True, "admin password accepted; cutover can write Pi-hole"))
        except PiholeError as exc:
            report.checks.append(Check("write_access", False, f"admin password rejected: {exc}"))
    else:
        report.checks.append(Check(
            "write_access", True if app_sudo else None,
            "Janus app password can write" if app_sudo
            else "unknown: Janus' app password is read-only until the cutover (needs the admin password then)",
            blocking=False))
    missing = [line for line in QUARANTINE_LINES if line not in lines]
    report.checks.append(Check("quarantine_rules", not missing, "dnsmasq quarantine tags present" if not missing
                               else f"Pi-hole is missing: {'; '.join(missing)} (recreate pihole with the updated compose)"))
    report.checks.append(_guest_check(net, lines, cfg.lease))
    report.checks.append(_range_check(net))
    report.checks.extend(_device_checks(db, net.gateway))
    try:
        diff = plan_sync(db, PiholeProvider(client, cfg), KIND, POLICIES)
        report.plan = {"to_add": len(diff.to_add), "to_remove": len(diff.to_remove), "unmanaged": len(diff.unmanaged)}
        report.checks.append(Check("sync_plan", True, f"{len(diff.to_add)} reservations to add, {len(diff.to_remove)} to remove, "
                                   f"{len(diff.unmanaged)} foreign lines left alone", blocking=False))
    except PiholeError as exc:
        report.checks.append(Check("sync_plan", False, f"cannot compute the sync plan: {exc}"))
    stamp = latest_backup(backup_dir())
    fresh = stamp is not None and now - stamp <= BACKUP_MAX_AGE
    if stamp is None:
        detail = "no backup yet: run `janus backup`"
    elif fresh:
        detail = f"latest backup {stamp:%Y-%m-%d %H:%M} UTC"
    else:
        detail = f"latest backup {stamp:%Y-%m-%d %H:%M} UTC is older than 24 h: run `janus backup`"
    report.checks.append(Check("backup", fresh, detail))
    return report


def dump_database(db: Session) -> dict[str, list[dict[str, Any]]]:
    meta = MetaData()
    meta.reflect(bind=db.get_bind())
    data: dict[str, list[dict[str, Any]]] = {}
    for name, table in sorted(meta.tables.items()):
        if name in SKIP_TABLES:
            continue
        data[name] = [dict(row._mapping) for row in db.execute(table.select())]
    return data


def take_backup(db: Session, client: PiholeAdmin, *, now: datetime | None = None, directory: Path | None = None) -> Path:
    now = now or datetime.now(UTC)
    target = (directory or backup_dir()) / now.strftime("%Y%m%d-%H%M%S")
    target.mkdir(parents=True, exist_ok=False)
    (target / "pihole-teleporter.zip").write_bytes(client.teleporter())
    (target / "janus.json").write_text(json.dumps(dump_database(db), default=str, indent=1))
    return target


def dhcp_config(net: NetConfig, lease: str) -> dict[str, Any]:
    return {
        "active": True,
        "start": net.quarantine_start,
        "end": net.quarantine_end,
        "router": net.gateway,
        "netmask": str(IPv4Network(net.subnet, strict=False).netmask),
        "leaseTime": lease,
        "ipv6": False,
    }


def cutover(db: Session, admin: PiholeAdmin, cfg: PiholeConfig, *, dhcp_kind: str | None) -> dict[str, Any]:
    report = preflight(db, admin, cfg, dhcp_kind=dhcp_kind, admin=admin)
    if not report.ready:
        raise RuntimeError("preflight is not green: " + "; ".join(c.detail for c in report.checks if c.blocking and not c.ok))
    net = load_netconfig(db)
    admin.patch_config({"webserver": {"api": {"app_sudo": True}}})
    store = PiholeProvider(admin, cfg)
    diff = apply_sync(db, store, KIND, POLICIES)
    admin.patch_config({"dhcp": dhcp_config(net, cfg.lease)})
    set_sync_mode(db, "apply", "cli cutover")
    db.commit()
    return {"dhcp": dhcp_config(net, cfg.lease), "sync_mode": load_sync_mode(db),
            "reservations": diff.as_dict(store.describe)}


def rollback(db: Session, admin: PiholeAdmin) -> dict[str, Any]:
    admin.patch_config({"dhcp": {"active": False}})
    admin.patch_config({"webserver": {"api": {"app_sudo": False}}})
    set_sync_mode(db, "dry-run", "cli rollback")
    db.commit()
    return {"dhcp": {"active": False}, "sync_mode": load_sync_mode(db)}
