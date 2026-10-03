from collections.abc import Callable
from typing import Protocol

from sqlalchemy.orm import Session

from app.events import record_event
from app.net.mac import normalize_mac
from app.pihole.reservations import HostDiff, desired_hosts, diff_hosts, managed_macs, remember_written, written_macs
from app.providers.pihole.client import PiholeError


class HostStore(Protocol):
    def list_hosts(self) -> list[str]: ...
    def add_host(self, line: str) -> None: ...
    def remove_host(self, line: str) -> None: ...


def plan_sync(db: Session, client: HostStore, lease: str) -> HostDiff:
    current = client.list_hosts()
    return diff_hosts(desired_hosts(db, lease), current, managed_macs(db, current, lease))


def _write(operation: Callable[[str], None], line: str, diff: HostDiff) -> bool:
    try:
        operation(line)
    except PiholeError as exc:
        if not exc.rejected:
            raise
        diff.failed.append(f"{line}: {exc}")
        return False
    return True


def apply_sync(db: Session, client: HostStore, lease: str) -> HostDiff:
    diff = plan_sync(db, client, lease)
    added: list[str] = []
    removed: list[str] = []
    try:
        for raw in diff.to_remove:
            if _write(client.remove_host, raw, diff):
                removed.append(raw)
        for host in diff.to_add:
            line = host.render()
            if _write(client.add_host, line, diff):
                added.append(line)
    finally:
        if added:
            remember_written(db, (written_macs(db) or set()) | {normalize_mac(line.split(",")[0]) for line in added})
        if added or removed:
            record_event(db, "sync.applied", None, {"added": added, "removed": removed})
        if diff.failed:
            record_event(db, "sync.failed", None, {"failed": list(diff.failed)})
    return diff
