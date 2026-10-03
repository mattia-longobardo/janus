import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app import guests
from app.netconfig import load_netconfig
from app.notify.config import channel_ready
from app.providers import runtime
from app.providers.base import Policy, Role
from app.providers.config import load_role
from app.providers.runtime import providers_feature

log = logging.getLogger(__name__)


def guests_feature(db: Session) -> dict[str, Any]:
    """Guests work with a DHCP provider that supports them, or with none (Janus only keeps the list). Without a
    pool Pi-hole guests would get quarantine addresses, hence no router: the page warns when `pool` is false.
    color/icon are the guests' look, so every page draws them without its own request."""
    look = guests.SETTINGS.load(db)
    return {
        "enabled": Policy.GUEST in runtime.policies(db) or load_role(db, Role.DHCP) is None,
        "pool": bool(load_netconfig(db).guest_pool()),
        "color": look["color"],
        "icon": look["icon"],
    }


# One entry per optional area of the web app; the frontend hides what is off.
FEATURE_PROVIDERS: dict[str, Callable[[Session], dict[str, Any]]] = {
    "notify": channel_ready,
    "providers": providers_feature,
    "guests": guests_feature,
}


def collect(db: Session) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, provider in FEATURE_PROVIDERS.items():
        try:
            out[name] = provider(db)
        except Exception:
            log.exception("feature provider %s failed", name)
            db.rollback()   # a failed query must not poison the session for the next provider
            out[name] = {}
    return out
