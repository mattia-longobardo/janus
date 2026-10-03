from typing import Self

from app.providers.base import CurrentEntry, ProviderError, Reservation


class FakeStore:
    """In-memory ReservationStore + LeaseControl. Entries it creates use the key "mac,ip,hostname,policy"."""

    def __init__(self, entries: list[CurrentEntry] | None = None, *, fail: bool = False,
                 reject: set[str] | None = None, drop_after_writes: int | None = None) -> None:
        self.entries = list(entries or [])
        self.fail = fail
        self.reject = reject or set()   # MACs whose addition the provider refuses (HTTP 400)
        self.drop_after_writes = drop_after_writes
        self.writes: list[tuple[str, str]] = []

    def _write(self, kind: str, what: str, mac: str | None = None) -> None:
        if self.drop_after_writes is not None and len(self.writes) >= self.drop_after_writes:
            raise ProviderError("fake provider unreachable: connection reset")
        if kind == "add" and mac in self.reject:
            raise ProviderError(f"add {what} failed: HTTP 400 invalid", status=400)
        self.writes.append((kind, what))

    def __enter__(self) -> Self:
        if self.fail:
            raise ProviderError("fake provider unreachable: connection refused")
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def describe(self, reservation: Reservation) -> str:
        r = reservation
        return f"{r.mac},{r.ip or ''},{r.hostname},{r.policy}"

    def list_reservations(self) -> list[CurrentEntry]:
        if self.fail:
            raise ProviderError("fake provider unreachable: connection refused")
        return list(self.entries)

    def add_reservation(self, reservation: Reservation) -> None:
        key = self.describe(reservation)
        self._write("add", key, reservation.mac)
        self.entries.append(CurrentEntry(key, key, reservation.mac, reservation.ip, reservation))

    def remove_reservation(self, entry: CurrentEntry) -> None:
        self._write("remove", entry.key)
        self.entries.remove(entry)

    def force_renew(self, mac: str, ip: str | None) -> None:
        self._write("renew", mac)
