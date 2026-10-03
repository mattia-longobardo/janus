"""The provider: translates Janus' Reservation / Policy model to the router and back."""
from typing import Self

from pydantic import BaseModel

from app.net.mac import normalize_mac
from app.providers._template.client import TemplateClient
from app.providers.base import CurrentEntry, Policy, Reservation

KIND = "template"
# The policies this router can really enforce. Anything not listed here is refused with a 409 before it
# reaches the router, never silently stored as FULL.
POLICIES = frozenset({Policy.FULL})


class TemplateConfig(BaseModel):
    url: str
    token: str = ""     # listed in SPEC.secret_fields: stored encrypted, never sent back to the browser


class TemplateProvider:
    def __init__(self, client: TemplateClient, config: TemplateConfig) -> None:
        self.client = client
        self.config = config

    def __enter__(self) -> Self:
        self.client.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.client.__exit__(*exc_info)

    # ReservationStore (Capability.RESERVATIONS)
    def list_reservations(self) -> list[CurrentEntry]:
        """Return EVERY entry the router holds, Janus' and the owner's own alike.

        `reservation=None` marks one Janus cannot interpret: it is reported but never removed.
        `canonical=False` marks a Janus entry written in an outdated format: it is rewritten.
        """
        entries = []
        for raw in self.client.list_reservations():
            # TODO(provider-author): map the router's record to a Reservation (mac, hostname, ip, policy).
            mac = normalize_mac(raw["mac"])
            reservation = Reservation(mac=mac, hostname=raw["name"], ip=raw.get("ip"), policy=Policy.FULL)
            entries.append(CurrentEntry(key=str(raw["id"]), display=f"{mac} {raw.get('ip') or ''}".strip(),
                                        mac=mac, ip=raw.get("ip"), reservation=reservation))
        return entries

    def add_reservation(self, reservation: Reservation) -> None:
        self.client.add_reservation(reservation.mac, reservation.ip, reservation.hostname)

    def remove_reservation(self, entry: CurrentEntry) -> None:
        self.client.remove_reservation(entry.key)

    def describe(self, reservation: Reservation) -> str:
        """The line shown in the sync plan (dry-run) for this reservation."""
        return f"{reservation.mac} {reservation.ip or 'dynamic'} {reservation.hostname}"

    # HealthCheck (optional): used by Settings "Test connection". Return a short summary, or raise ProviderError.
    def check(self) -> str:
        # TODO(provider-author): make one cheap authenticated call (login, version, ...) and describe the result.
        self.client.list_reservations()
        return "Connected"
