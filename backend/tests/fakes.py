from typing import Self

from app.providers.pihole.client import PiholeError


class FakePihole:
    def __init__(self, hosts: list[str] | None = None, *, fail: bool = False,
                 reject: set[str] | None = None, drop_after_writes: int | None = None) -> None:
        self.hosts = list(hosts or [])
        self.fail = fail
        self.reject = reject or set()
        self.drop_after_writes = drop_after_writes
        self.writes: list[tuple[str, str]] = []
        self.queries: list[dict] = []

    def _write(self, kind: str, line: str) -> None:
        if self.drop_after_writes is not None and len(self.writes) >= self.drop_after_writes:
            raise PiholeError("Pi-hole unreachable: connection reset")
        if line in self.reject:
            raise PiholeError(f"PUT {line} failed: HTTP 400 invalid", status=400)
        self.writes.append((kind, line))

    def __enter__(self) -> Self:
        if self.fail:
            raise PiholeError("Pi-hole unreachable: connection refused")
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def list_hosts(self) -> list[str]:
        if self.fail:
            raise PiholeError("Pi-hole unreachable: connection refused")
        return list(self.hosts)

    def add_host(self, line: str) -> None:
        self._write("add", line)
        self.hosts.append(line)

    def remove_host(self, line: str) -> None:
        self._write("remove", line)
        self.hosts.remove(line)

    def list_queries(self, client_ip: str, since: int, until: int, length: int = 5000,
                     disk: bool = False) -> tuple[list[dict], int]:
        if self.fail:
            raise PiholeError("Pi-hole unreachable: connection refused")
        self.last_query = {"client_ip": client_ip, "since": since, "until": until, "length": length, "disk": disk}
        matches = [q for q in self.queries if q["client"]["ip"] == client_ip and since <= q["time"] <= until]
        return matches[:length], getattr(self, "reported_total", len(matches))

    def revoke_lease(self, ip: str) -> None:
        self._write("revoke", ip)

    def close(self) -> None:
        return None
