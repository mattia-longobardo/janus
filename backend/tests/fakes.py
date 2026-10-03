import copy
from typing import Any, Self

from app.providers.pihole.client import PiholeError
from app.providers.pihole.cutover import QUARANTINE_LINES


class FakeConfig:
    """Pi-hole's /api/config: GET returns the subtree under its path, PATCH merges objects and replaces arrays."""

    config: dict[str, Any]
    patches: list[dict[str, Any]]
    fail_config: bool = False
    patch_status: int | None = None   # set to e.g. 403 to refuse PATCH (app password without app_sudo)

    def get_config(self, path: str) -> dict[str, Any]:
        if self.fail_config:
            raise PiholeError("Pi-hole unreachable: boom")
        parts = path.split("/")
        node: Any = self.config
        for part in parts:
            node = node[part]
        out = copy.deepcopy(node)
        for part in reversed(parts[1:]):
            out = {part: out}
        return {parts[0]: out}

    def patch_config(self, config: dict[str, Any]) -> None:
        if self.patch_status is not None:
            raise PiholeError(f"PATCH /api/config failed: HTTP {self.patch_status} forbidden", status=self.patch_status)
        self.patches.append(config)
        _merge(self.config, copy.deepcopy(config))


def _merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value


class FakeAdmin(FakeConfig):
    def __init__(self, *, lines=QUARANTINE_LINES, app_sudo=False, fail=False, config=None):
        self.config = config if config is not None else {
            "dhcp": {"active": False}, "misc": {"dnsmasq_lines": ["address=/local/192.168.1.220", *lines]},
            "webserver": {"api": {"app_sudo": app_sudo}}}
        self.hosts: list[str] = []
        self.patches: list[dict] = []
        self.fail_config = fail

    def teleporter(self):
        return b"PK\x03\x04zip"

    def list_hosts(self):
        return list(self.hosts)

    def add_host(self, line):
        self.hosts.append(line)

    def remove_host(self, line):
        self.hosts.remove(line)


class FakePihole(FakeConfig):
    def __init__(self, hosts: list[str] | None = None, *, fail: bool = False,
                 reject: set[str] | None = None, drop_after_writes: int | None = None) -> None:
        self.hosts = list(hosts or [])
        self.fail = fail
        self.reject = reject or set()
        self.drop_after_writes = drop_after_writes
        self.writes: list[tuple[str, str]] = []
        self.queries: list[dict] = []
        self.config: dict[str, Any] = {"misc": {"dnsmasq_lines": list(QUARANTINE_LINES)}}
        self.patches: list[dict[str, Any]] = []

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
