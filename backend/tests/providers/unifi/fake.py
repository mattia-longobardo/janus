"""In-memory UniFi controller with the public interface of UnifiClient."""
from typing import Any, Self

from app.providers.unifi.client import UnifiError

LAN = {"_id": "n1", "name": "LAN", "purpose": "corporate", "ip_subnet": "192.168.1.1/24"}


class FakeUnifi:
    def __init__(
        self,
        users: list[dict[str, Any]] | None = None,
        *,
        offline: set[str] | None = None,
        online: list[dict[str, Any]] | None = None,
        devices: list[dict[str, Any]] | None = None,
        networks: list[dict[str, Any]] | None = None,
        fail: bool = False,
    ) -> None:
        self.users: dict[str, dict[str, Any]] = {str(u["mac"]).lower(): dict(u) for u in users or []}
        self.offline = {m.lower() for m in offline or set()}
        self.online = list(online or [])
        self.devices = list(devices or [])
        self.networks = list(networks if networks is not None else [LAN])
        self.fail = fail
        self.commands: list[tuple[str, str]] = []           # stamgr calls, in order
        self.updates: list[tuple[str, dict[str, Any]]] = []  # PUT rest/user/<id> bodies, in order
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True

    def _check(self) -> None:
        if self.fail:
            raise UnifiError("UniFi unreachable: connection refused")

    def list_known(self) -> list[dict[str, Any]]:
        self._check()
        return [dict(u) for u in self.users.values()]

    def list_online(self) -> list[dict[str, Any]]:
        self._check()
        return [dict(s) for s in self.online]

    def list_networks(self) -> list[dict[str, Any]]:
        self._check()
        return [dict(n) for n in self.networks]

    def list_devices(self) -> list[dict[str, Any]]:
        self._check()
        return [dict(d) for d in self.devices]

    def _by_id(self, user_id: str) -> dict[str, Any]:
        found = next((u for u in self.users.values() if u["_id"] == user_id), None)
        if found is None:
            raise UnifiError(f"PUT rest/user/{user_id}: HTTP 400", status=400)
        return found

    def ensure_known(self, mac: str, name: str) -> dict[str, Any]:
        self._check()
        mac_lower = mac.lower()
        if mac_lower not in self.users:
            self.users[mac_lower] = {"_id": f"u{len(self.users) + 1}", "mac": mac_lower, "name": name}
        return dict(self.users[mac_lower])

    def update_user(self, user_id: str, fields: dict[str, Any]) -> None:
        self._check()
        self._by_id(user_id).update(fields)
        self.updates.append((user_id, dict(fields)))

    def set_fixed_ip(self, user_id: str, *, ip: str | None, network_id: str | None, name: str) -> None:
        self.update_user(user_id, {"use_fixedip": ip is not None, "fixed_ip": ip or "", "network_id": network_id or "",
                                   "name": name})

    def stamgr(self, cmd: str, mac: str) -> None:
        self._check()
        mac_lower = mac.lower()
        if cmd == "kick-sta" and mac_lower in self.offline:
            raise UnifiError("api.err.UnknownStation", status=400)
        self.commands.append((cmd, mac_lower))
        if cmd in ("block-sta", "unblock-sta"):
            user = self.users.setdefault(mac_lower, {"_id": f"u{len(self.users) + 1}", "mac": mac_lower})
            user["blocked"] = cmd == "block-sta"
