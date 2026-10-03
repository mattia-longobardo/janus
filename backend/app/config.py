from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JANUS_", extra="ignore")

    database_url: str = "postgresql+psycopg://janus:janus@localhost:5432/janus"
    internal_token: str = ""
    secret_key: str = ""
    pihole_url: str = ""
    pihole_password: str = ""
    subnet: str = "192.168.1.0/24"
    gateway: str = "192.168.1.1"
    quarantine_start: str = "192.168.1.240"
    quarantine_end: str = "192.168.1.254"
    reservation_lease: str = "24h"
    sync_mode: Literal["dry-run", "apply"] = "dry-run"
    reconcile_interval_s: int = 300
    heartbeat_path: str = "/tmp/janus-worker.heartbeat"
    timezone: str = "Europe/Rome"
    redis_url: str = "redis://localhost:6379/3"
    gotify_url: str = ""
    gotify_token: str = ""
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_security: Literal["ssl", "starttls", "none"] = "ssl"
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_sender: str = ""
    notify_email: str = ""
    base_url: str = "https://janus.longobardo.me"
    presence_timeout_s: int = 300
    presence_interval_s: int = 60
    dispatch_interval_s: int = 15
    sentinel_interface: str = "enp5s0"
    sweep_interval_s: int = 60
    sentinel_heartbeat_path: str = "/tmp/janus-sentinel.heartbeat"
    sighting_retention_days: int = 30
    oui_path: str = "/usr/share/ieee-data/oui.csv"
    identity_interval_s: int = 60
    scan_poll_s: int = 30
    scan_host_timeout_s: int = 180
    scanner_heartbeat_path: str = "/tmp/janus-scanner.heartbeat"
    scan_window_start: str = "08:00"
    scan_window_end: str = "22:00"
    # --- B --- sign-in. The old Authentik env names keep working next to the JANUS_ ones.
    allowed_emails: str = ""
    oidc_id: str = Field("", validation_alias=AliasChoices("JANUS_OIDC_ID", "AUTH_AUTHENTIK_ID"))
    oidc_secret: str = Field("", validation_alias=AliasChoices("JANUS_OIDC_SECRET", "AUTH_AUTHENTIK_SECRET"))
    oidc_issuer: str = Field("", validation_alias=AliasChoices("JANUS_OIDC_ISSUER", "AUTH_AUTHENTIK_ISSUER"))
    oidc_name: str = Field("Authentik", validation_alias=AliasChoices("JANUS_OIDC_NAME"))
    # --- C --- network providers per role: "" = Pi-hole when JANUS_PIHOLE_PASSWORD is set, "none" = off.
    dhcp_provider: str = ""
    dns_provider: str = ""

    # --- E --- guest DHCP pool, "" = not defined.
    guest_start: str = ""
    guest_end: str = ""
    guests_interval_s: int = 60


settings = Settings()
