import threading
from typing import Any, Self
from urllib.parse import quote

import httpx

from app.providers.base import ProviderError


class PiholeError(ProviderError):
    pass


class SharedSession:
    """One Pi-hole login reused by concurrent API requests: Pi-hole refuses parallel logins (HTTP 429/401)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sid: str | None = None


_SHARED: dict[str, SharedSession] = {}
_SHARED_LOCK = threading.Lock()


def shared_session(base_url: str) -> SharedSession:
    with _SHARED_LOCK:
        return _SHARED.setdefault(base_url, SharedSession())


class PiholeClient:
    def __init__(
        self, base_url: str, password: str, *, http: httpx.Client | None = None, shared: SharedSession | None = None
    ) -> None:
        self._http = http or httpx.Client(base_url=base_url, timeout=10.0)
        self._password = password
        self._shared = shared
        self._sid: str | None = shared.sid if shared else None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _login(self) -> None:
        if self._shared is None:
            self._authenticate()
            return
        stale = self._sid
        with self._shared.lock:
            if self._shared.sid is not None and self._shared.sid != stale:
                self._sid = self._shared.sid
                return
            self._authenticate()
            self._shared.sid = self._sid

    def _authenticate(self) -> None:
        try:
            response = self._http.post("/api/auth", json={"password": self._password})
        except httpx.HTTPError as exc:
            raise PiholeError(f"Pi-hole unreachable: {exc}") from exc
        try:
            session = response.json().get("session", {})
        except ValueError:
            session = {}
        if response.status_code != 200 or not session.get("valid"):
            raise PiholeError(f"Pi-hole login failed: HTTP {response.status_code}")
        self._sid = session["sid"]

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._http.request(method, path, headers={"X-FTL-SID": self._sid or ""}, **kwargs)
        except httpx.HTTPError as exc:
            raise PiholeError(f"Pi-hole unreachable: {exc}") from exc

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._sid is None:
            self._login()
        response = self._send(method, path, **kwargs)
        if response.status_code == 401:
            self._login()
            response = self._send(method, path, **kwargs)
        if response.status_code >= 400:
            raise PiholeError(
                f"{method} {path} failed: HTTP {response.status_code} {response.text[:200]}", status=response.status_code
            )
        return response

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._request(method, path, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise PiholeError(
                f"{method} {path}: reply is not valid JSON ({response.text[:80]!r})", status=response.status_code
            ) from exc

    def _field(self, body: Any, path: str, *keys: str) -> Any:
        value = body
        try:
            for key in keys:
                value = value[key]
        except (KeyError, TypeError, IndexError) as exc:
            raise PiholeError(f"GET {path}: unexpected reply, missing {'.'.join(keys)}") from exc
        return value

    def list_hosts(self) -> list[str]:
        path = "/api/config/dhcp/hosts"
        return self._field(self._json("GET", path), path, "config", "dhcp", "hosts")

    def add_host(self, line: str) -> None:
        self._request("PUT", "/api/config/dhcp/hosts/" + quote(line, safe=""))

    def remove_host(self, line: str) -> None:
        self._request("DELETE", "/api/config/dhcp/hosts/" + quote(line, safe=""))

    def list_leases(self) -> list[dict[str, Any]]:
        return self._field(self._json("GET", "/api/dhcp/leases"), "/api/dhcp/leases", "leases")

    def list_queries(
        self, client_ip: str, since: int, until: int, length: int = 5000, disk: bool = False
    ) -> tuple[list[dict[str, Any]], int]:
        params: dict[str, Any] = {"client_ip": client_ip, "from": since, "until": until, "length": length}
        if disk:
            params["disk"] = "true"
        body = self._json("GET", "/api/queries", params=params)
        queries = self._field(body, "/api/queries", "queries")
        return queries, int(body.get("recordsFiltered", len(queries)))

    def revoke_lease(self, ip: str) -> None:
        self._request("DELETE", f"/api/dhcp/leases/{ip}")

    def close(self) -> None:
        if self._sid is not None and self._shared is None:
            try:
                self._http.delete("/api/auth", headers={"X-FTL-SID": self._sid})
            except httpx.HTTPError:
                pass
            self._sid = None
        self._http.close()
