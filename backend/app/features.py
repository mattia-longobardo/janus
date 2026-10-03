import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.notify.config import channel_ready
from app.providers.runtime import providers_feature

log = logging.getLogger(__name__)

# One entry per optional area of the web app; the frontend hides what is off.
FEATURE_PROVIDERS: dict[str, Callable[[Session], dict[str, Any]]] = {
    "notify": channel_ready,
    "providers": providers_feature,
}


def collect(db: Session) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, provider in FEATURE_PROVIDERS.items():
        try:
            out[name] = provider(db)
        except Exception:
            log.exception("feature provider %s failed", name)
            out[name] = {}
    return out
