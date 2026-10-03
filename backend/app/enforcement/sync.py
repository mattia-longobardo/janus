from collections.abc import Callable

from sqlalchemy.orm import Session

from app.enforcement.reservations import (
    ReservationDiff,
    desired_reservations,
    diff_reservations,
    managed_macs,
    remember_written,
    written_macs,
)
from app.events import record_event
from app.providers.base import Policy, ProviderError, ReservationStore


def plan_sync(db: Session, store: ReservationStore, kind: str, policies: frozenset[Policy]) -> ReservationDiff:
    current = store.list_reservations()
    return diff_reservations(
        desired_reservations(db, policies), current, managed_macs(db, kind, current), store.describe
    )


def _write(operation: Callable[[], None], label: str, diff: ReservationDiff) -> bool:
    try:
        operation()
    except ProviderError as exc:
        if not exc.rejected:
            raise
        diff.failed.append(f"{label}: {exc}")
        return False
    return True


def apply_sync(db: Session, store: ReservationStore, kind: str, policies: frozenset[Policy]) -> ReservationDiff:
    diff = plan_sync(db, store, kind, policies)
    added: list[str] = []
    added_macs: set[str] = set()
    removed: list[str] = []
    try:
        for entry in diff.to_remove:
            if _write(lambda e=entry: store.remove_reservation(e), entry.display, diff):
                removed.append(entry.display)
        for r in diff.to_add:
            label = store.describe(r)
            if _write(lambda r=r: store.add_reservation(r), label, diff):
                added.append(label)
                added_macs.add(r.mac)
    finally:
        if added_macs:
            remember_written(db, kind, (written_macs(db, kind) or set()) | added_macs)
        if added or removed:
            record_event(db, "sync.applied", None, {"added": added, "removed": removed})
        if diff.failed:
            record_event(db, "sync.failed", None, {"failed": list(diff.failed)})
    # Optional hook for provider settings that follow the reservations (e.g. Pi-hole's guest dhcp-range).
    after_sync = getattr(store, "after_sync", None)
    if after_sync is not None:
        after_sync(db)
    return diff
