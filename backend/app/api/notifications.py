from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.events import record_event
from app.models import NotificationRule
from app.notify.catalog import CATALOG, CHANNELS
from app.notify.config import EMAIL as EMAIL_STORE
from app.notify.config import GOTIFY, channel_ready
from app.notify.store import (
    MAX_PRIORITY,
    MIN_PRIORITY,
    NotifySettings,
    effective_priority,
    load_notify_settings,
    load_priorities,
    load_rules,
    save_notify_settings,
    save_priorities,
)
from app.settingsstore import SettingsError

router = APIRouter(prefix="/api/notifications", tags=["notifications"])
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
EMAIL = r"^$|^[^@\s]+@[^@\s]+\.[^@\s]+$"

STORES = {"gotify": GOTIFY, "email": EMAIL_STORE}


class SettingsIn(BaseModel):
    enabled: bool
    quiet_start: str | None = Field(default=None, pattern=HHMM)
    quiet_end: str | None = Field(default=None, pattern=HHMM)
    email_enabled: bool
    email_recipient: str = Field(default="", max_length=254, pattern=EMAIL)
    gotify_enabled: bool


class RuleIn(BaseModel):
    event_type: str
    email: bool
    gotify: bool
    priority: int | None = Field(default=None, ge=MIN_PRIORITY, le=MAX_PRIORITY, strict=True)


class ChannelsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gotify: dict[str, Any] | None = None
    email: dict[str, Any] | None = None


def _channels(db: Session) -> dict[str, Any]:
    ready = channel_ready(db)
    return {name: {"values": store.view(db), "source": store.sources(db), "ready": ready[name]}
            for name, store in STORES.items()}


def _rules(db: Session) -> list[dict[str, Any]]:
    stored = load_rules(db)
    priorities = load_priorities(db)
    return [
        {"event_type": kind, "label": spec.label,
         "email": stored.get((kind, "email"), spec.email), "gotify": stored.get((kind, "gotify"), spec.gotify),
         "priority": effective_priority(kind, priorities), "default_priority": spec.priority}
        for kind, spec in CATALOG.items()
        if kind != "notify.test"
    ]


@router.get("")
def get_notifications(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"settings": asdict(load_notify_settings(db)), "rules": _rules(db)}


@router.get("/channels")
def get_channels(db: Session = Depends(get_db)) -> dict[str, Any]:
    return _channels(db)


@router.put("/channels")
def put_channels(body: ChannelsPatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    changed: dict[str, list[str]] = {}
    try:
        for name, patch in body.model_dump(exclude_none=True).items():
            STORES[name].update(db, patch)
            changed[name] = sorted(patch)
    except SettingsError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if changed:
        record_event(db, "settings.channels", None, {"changed": changed})
    db.commit()
    return _channels(db)


@router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    ns = NotifySettings(**body.model_dump())
    save_notify_settings(db, ns)
    db.commit()
    return asdict(ns)


@router.put("/rules")
def put_rules(body: list[RuleIn], db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    for rule in body:
        if rule.event_type not in CATALOG or rule.event_type == "notify.test":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown event type {rule.event_type!r}")
    priorities = load_priorities(db)
    for rule in body:
        db.merge(NotificationRule(event_type=rule.event_type, channel="email", enabled=rule.email))
        db.merge(NotificationRule(event_type=rule.event_type, channel="gotify", enabled=rule.gotify))
        if "priority" in rule.model_fields_set:
            if rule.priority is None or rule.priority == CATALOG[rule.event_type].priority:
                priorities.pop(rule.event_type, None)
            else:
                priorities[rule.event_type] = rule.priority
    save_priorities(db, priorities)
    db.commit()
    return _rules(db)


@router.post("/test/{channel}", status_code=status.HTTP_202_ACCEPTED)
def test_channel(channel: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    if channel not in CHANNELS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown channel")
    if not channel_ready(db)[channel]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{channel} is not configured")
    record_event(db, "notify.test", None, {"channel": channel})
    db.commit()
    return {"queued": True}
