"""UniFi provider (stream D): reservations, guest and block policies, reconnect on a UniFi Network controller."""
from app.config import settings
from app.db import SessionLocal
from app.netconfig import load_netconfig
from app.providers.base import Capability, ProviderSpec, Role
from app.providers.unifi import api
from app.providers.unifi.client import UnifiClient
from app.providers.unifi.provider import KIND, POLICIES, UnifiConfig, UnifiProvider


def _janus_lan() -> tuple[str, str]:
    """Janus' subnet and gateway, read when the provider first needs the LAN network (not when it is opened)."""
    with SessionLocal() as db:
        net = load_netconfig(db)
    return net.subnet, net.gateway


def open_unifi(cfg: UnifiConfig) -> UnifiProvider:
    client = UnifiClient(cfg.url, username=cfg.username, password=cfg.password, site=cfg.site,
                         unifi_os=cfg.unifi_os, verify_tls=cfg.verify_tls)
    return UnifiProvider(client, cfg, lan=lambda: _janus_lan())


SPEC = ProviderSpec(
    kind=KIND,
    label="UniFi",
    description="UniFi Network: fixed-IP reservations, guest and blocked clients, reconnect, client list.",
    roles=frozenset({Role.DHCP}),
    capabilities=frozenset({Capability.RESERVATIONS, Capability.FORCE_RENEW, Capability.CLIENT_INVENTORY}),
    policies=POLICIES,
    config_model=UnifiConfig,
    provider_class=UnifiProvider,
    secret_fields=frozenset({"password"}),
    env_defaults=lambda: {"url": settings.unifi_url, "username": settings.unifi_username,
                          "password": settings.unifi_password},
    open=open_unifi,
    router=api.router,
    docs_url="https://ubntwiki.com/products/software/unifi-controller/api",
)
