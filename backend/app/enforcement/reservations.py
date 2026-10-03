from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Access, Device, Setting
from app.providers.base import CurrentEntry, Policy, Reservation

# Access levels that become a reservation with a fixed IP, and the policy each maps to.
_ADDRESSED: dict[Access, Policy] = {Access.authorized: Policy.FULL, Access.lan_only: Policy.LAN_ONLY}


@dataclass
class ReservationDiff:
    to_add: list[Reservation] = field(default_factory=list)
    to_remove: list[CurrentEntry] = field(default_factory=list)
    unmanaged: list[CurrentEntry] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.to_add or self.to_remove)

    def as_dict(self, describe: Callable[[Reservation], str]) -> dict[str, Any]:
        return {
            "to_add": [describe(r) for r in self.to_add],
            "to_remove": [e.display for e in self.to_remove],
            "unmanaged": [e.display for e in self.unmanaged],
            "failed": list(self.failed),
        }


def desired_reservations(db: Session, policies: frozenset[Policy]) -> set[Reservation]:
    """What the provider should hold. Policies the provider does not support are left out here; approving a
    device with such a policy is refused upfront."""
    wanted = {access: policy for access, policy in _ADDRESSED.items() if policy in policies}
    desired: set[Reservation] = set()
    if wanted:
        rows = db.scalars(
            select(Device).where(
                Device.mac.is_not(None), Device.static_ip.is_not(None), Device.access.in_(list(wanted))
            )
        )
        desired |= {Reservation(d.mac, d.hostname, d.static_ip, wanted[d.access]) for d in rows}
    if Policy.BLOCKED in policies:
        rows = db.scalars(select(Device).where(Device.mac.is_not(None), Device.access == Access.blocked))
        desired |= {Reservation(d.mac, d.hostname, None, Policy.BLOCKED) for d in rows}
    return desired


def written_key(kind: str) -> str:
    return f"provider.{kind}.written_macs"


def written_macs(db: Session, kind: str) -> set[str] | None:
    row = db.get(Setting, written_key(kind))
    return set(row.value) if row is not None and isinstance(row.value, list) else None


def remember_written(db: Session, kind: str, macs: set[str]) -> None:
    db.merge(Setting(key=written_key(kind), value=sorted(macs)))


def managed_macs(db: Session, kind: str, current: list[CurrentEntry]) -> set[str]:
    """MACs Janus manages on this provider: every device it knows plus every MAC it has ever written there, so
    the reservation of a deleted device is removed too. Before anything is recorded, entries in Janus' exact
    current format are recognised as Janus' own."""
    known = set(db.scalars(select(Device.mac).where(Device.mac.is_not(None))))
    written = written_macs(db, kind)
    if written is None:
        written = {e.reservation.mac for e in current if e.reservation is not None and e.canonical}
        remember_written(db, kind, written)
    return known | written


def _sort_key(r: Reservation) -> tuple[str, str, str, str]:
    return (r.mac, r.ip or "", r.hostname, r.policy)


def diff_reservations(
    desired: set[Reservation],
    current: list[CurrentEntry],
    managed: set[str] | None = None,
    describe: Callable[[Reservation], str] | None = None,
) -> ReservationDiff:
    """Entries Janus does not manage (MAC neither known nor written by Janus) are reported, never removed.

    An addition that would give the provider two reservations with the same IP or MAC is refused and reported in
    `failed`: dnsmasq (and most routers) reject such a configuration, and dnsmasq stops answering DNS."""
    label = describe or (lambda r: f"{r.mac} {r.ip or ''} {r.hostname}")
    diff = ReservationDiff()
    own: list[CurrentEntry] = []
    for entry in current:
        if entry.reservation is None or (managed is not None and entry.mac not in managed):
            diff.unmanaged.append(entry)
        else:
            own.append(entry)
    keep = [e for e in own if e.canonical and e.reservation in desired]
    diff.to_remove = sorted((e for e in own if e not in keep), key=lambda e: e.key)
    taken_ips = {e.ip: e.display for e in keep + diff.unmanaged if e.ip}
    taken_macs = {e.mac: e.display for e in keep + diff.unmanaged if e.mac}
    present = {e.reservation for e in keep}
    for r in sorted(desired - present, key=_sort_key):
        clash = (taken_ips.get(r.ip) if r.ip else None) or taken_macs.get(r.mac)
        if clash is not None:
            diff.failed.append(f"{label(r)}: would duplicate {clash}, skipped")
            continue
        diff.to_add.append(r)
        if r.ip:
            taken_ips[r.ip] = label(r)
        taken_macs[r.mac] = label(r)
    return diff
