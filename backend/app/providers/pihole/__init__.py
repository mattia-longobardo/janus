from app.config import settings
from app.providers.base import Capability, ProviderSpec, Role
from app.providers.pihole import api
from app.providers.pihole.client import PiholeClient, shared_session
from app.providers.pihole.provider import KIND, POLICIES, PiholeConfig, PiholeProvider


def open_pihole(cfg: PiholeConfig) -> PiholeProvider:
    """One Pi-hole login per URL, shared by every caller: Pi-hole refuses parallel logins."""
    return PiholeProvider(PiholeClient(cfg.url, cfg.password, shared=shared_session(cfg.url)), cfg)


SPEC = ProviderSpec(
    kind=KIND,
    label="Pi-hole",
    description="Pi-hole v6: DHCP reservations with quarantine for unknown devices, DNS query log.",
    roles=frozenset({Role.DHCP, Role.DNS}),
    capabilities=frozenset({Capability.RESERVATIONS, Capability.FORCE_RENEW, Capability.QUARANTINE,
                            Capability.DHCP_SERVER, Capability.DNS_QUERY_LOG, Capability.DNS_PROBE}),
    policies=POLICIES,
    config_model=PiholeConfig,
    provider_class=PiholeProvider,
    secret_fields=frozenset({"password"}),
    env_defaults=lambda: {"url": settings.pihole_url, "password": settings.pihole_password,
                          "lease": settings.reservation_lease},
    open=open_pihole,
    router=api.router,
    docs_url="https://docs.pi-hole.net/api/",
)
