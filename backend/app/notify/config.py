from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.notify.channels import EmailChannel, GotifyChannel
from app.notify.store import load_notify_settings
from app.settingsstore import OverlayStore, SettingsError, StoreField


def _url(value: Any) -> str:
    text = str(value).strip().rstrip("/")
    if not text.startswith(("http://", "https://")):
        raise SettingsError("url: must start with http:// or https://")
    return text


def _port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise SettingsError("port: must be a number") from None
    if not 1 <= port <= 65535:
        raise SettingsError("port: must be between 1 and 65535")
    return port


def _security(value: Any) -> str:
    if value not in ("ssl", "starttls", "none"):
        raise SettingsError("security: must be ssl, starttls or none")
    return value


def _text(value: Any) -> str:
    return str(value).strip()


GOTIFY = OverlayStore("notify.gotify", [
    StoreField("url", lambda: settings.gotify_url, validate=_url),
    StoreField("token", lambda: settings.gotify_token, secret=True),
])

EMAIL = OverlayStore("notify.email", [
    StoreField("host", lambda: settings.smtp_host, validate=_text),
    StoreField("port", lambda: settings.smtp_port, validate=_port),
    StoreField("security", lambda: settings.smtp_security, validate=_security),
    StoreField("user", lambda: settings.smtp_user, validate=_text),
    StoreField("password", lambda: settings.smtp_password, secret=True),
    StoreField("sender", lambda: settings.smtp_sender, validate=_text),
])


def build_senders(db: Session) -> dict[str, Any]:
    """Rebuilt on every dispatch so a change saved in Settings applies without restarting the worker."""
    g, e = GOTIFY.load(db), EMAIL.load(db)
    return {
        "email": EmailChannel(e["host"], e["port"], e["user"], e["password"], e["sender"], security=e["security"]),
        "gotify": GotifyChannel(g["url"], g["token"]),
    }


def channel_ready(db: Session) -> dict[str, bool]:
    ns = load_notify_settings(db)
    return {name: sender.ready(ns) for name, sender in build_senders(db).items()}
