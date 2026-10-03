import json
from typing import Any, Literal, Self

import httpx

from app.providers.base import ProviderError


class UnifiError(ProviderError):
    pass


class UnifiClient:
    """Client for the classic UniFi Network API (UniFi OS console or standalone controller).

    Logs in on first use; the session cookie lives in the httpx client. UniFi OS also hands out a CSRF token at
    login that every write must send back."""

    def __init__(
        self,
        base_url: str,
        *,
        username: str,
        password: str,
        site: str = "default",
        unifi_os: bool = True,
        verify_tls: bool = False,
        http: httpx.Client | None = None,
    ) -> None:
        self._http = http or httpx.Client(base_url=base_url, verify=verify_tls, timeout=10.0)
        self._username = username
        self._password = password
        self._site = site
        self._unifi_os = unifi_os
        self._prefix = "/proxy/network" if unifi_os else ""
        self._logged_in = False
        self._csrf: str | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _login(self) -> None:
        path = "/api/auth/login" if self._unifi_os else "/api/login"
        try:
            response = self._http.post(path, json={"username": self._username, "password": self._password})
        except httpx.HTTPError as exc:
            raise UnifiError(f"UniFi unreachable: {exc}") from exc
        if response.status_code != 200:
            raise UnifiError(f"UniFi login failed: HTTP {response.status_code}")
        self._csrf = response.headers.get("x-csrf-token")
        self._logged_in = True

    def _send(self, method: str, url: str, body: Any) -> httpx.Response:
        headers: dict[str, str] = {}
        content = None
        if body is not None:
            headers["content-type"] = "application/json"
            content = json.dumps(body, separators=(",", ":")).encode()
        if method != "GET" and self._csrf:
            headers["x-csrf-token"] = self._csrf
        try:
            response = self._http.request(method, url, headers=headers, content=content)
        except httpx.HTTPError as exc:
            raise UnifiError(f"UniFi unreachable: {exc}") from exc
        # UniFi OS rotates the token on responses.
        self._csrf = response.headers.get("x-updated-csrf-token", self._csrf)
        return response

    def _json(self, method: str, path: str, body: Any = None) -> Any:
        url = f"{self._prefix}/api/s/{self._site}/{path}"
        if not self._logged_in:
            self._login()
        response = self._send(method, url, body)
        if response.status_code == 401:
            self._login()
            response = self._send(method, url, body)
        if response.status_code >= 400:
            raise UnifiError(f"{method} {url}: HTTP {response.status_code}", status=response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise UnifiError(f"{method} {url}: reply is not JSON") from exc
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        if meta.get("rc") == "error":
            raise UnifiError(f"{method} {url}: {meta.get('msg', 'error')}", status=400)
        return payload

    def _data(self, path: str) -> list[dict[str, Any]]:
        payload = self._json("GET", path)
        try:
            return payload["data"]
        except (KeyError, TypeError) as exc:
            raise UnifiError(f"GET {path}: unexpected reply, missing data") from exc

    def list_known(self) -> list[dict[str, Any]]:
        return self._data("rest/user")

    def list_online(self) -> list[dict[str, Any]]:
        return self._data("stat/sta")

    def list_networks(self) -> list[dict[str, Any]]:
        return self._data("rest/networkconf")

    def list_devices(self) -> list[dict[str, Any]]:
        """Access points and switches (`mac`, `name`)."""
        return self._data("stat/device")

    def _find_known(self, mac_lower: str) -> dict[str, Any] | None:
        return next((u for u in self.list_known() if str(u.get("mac", "")).lower() == mac_lower), None)

    def ensure_known(self, mac: str, name: str) -> dict[str, Any]:
        """The known-client record for `mac`; created first when the controller has never seen the device."""
        mac_lower = mac.lower()
        found = self._find_known(mac_lower)
        if found is not None:
            return found
        self._json("POST", "group/user", {"objects": [{"data": {"mac": mac_lower, "name": name}}]})
        found = self._find_known(mac_lower)
        if found is None:
            raise UnifiError(f"client {mac_lower} not found after creating it")
        return found

    def update_user(self, user_id: str, fields: dict[str, Any]) -> None:
        """Change only the given fields of a known client (`name`, `note`/`noted`, ...)."""
        self._json("PUT", f"rest/user/{user_id}", fields)

    def set_fixed_ip(self, user_id: str, *, ip: str | None, network_id: str | None, name: str) -> None:
        body = {"use_fixedip": ip is not None, "fixed_ip": ip or "", "network_id": network_id or "", "name": name}
        self.update_user(user_id, body)

    def stamgr(self, cmd: Literal["block-sta", "unblock-sta", "kick-sta"], mac: str) -> None:
        self._json("POST", "cmd/stamgr", {"cmd": cmd, "mac": mac.lower()})

    def close(self) -> None:
        self._http.close()
