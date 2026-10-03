"""HTTP client for the router. Keep it thin: one method per router call, no Janus concepts in here."""
from typing import Any, Self

import httpx

from app.providers.base import ProviderError

TIMEOUT = 10.0   # never wait on a router forever: the worker and the web requests share this code


class TemplateClient:
    def __init__(self, url: str, token: str) -> None:
        self.http = httpx.Client(base_url=url, timeout=TIMEOUT, headers={"Authorization": f"Bearer {token}"})

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.http.close()

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Turn every transport or HTTP failure into a ProviderError; a 4xx keeps its status (a one-off refusal)."""
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"router unreachable: {exc}") from exc
        if response.is_error:
            raise ProviderError(f"router answered {response.status_code}", status=response.status_code)
        return response.json() if response.content else None

    def list_reservations(self) -> list[dict[str, Any]]:
        # TODO(provider-author): call your router's "list fixed-IP clients" endpoint.
        return self.request("GET", "/reservations")

    def add_reservation(self, mac: str, ip: str | None, hostname: str) -> None:
        # TODO(provider-author): create the fixed-IP entry.
        self.request("POST", "/reservations", json={"mac": mac, "ip": ip, "name": hostname})

    def remove_reservation(self, key: str) -> None:
        # TODO(provider-author): delete the entry whose native id is `key`.
        self.request("DELETE", f"/reservations/{key}")
