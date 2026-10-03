from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.events import record_event
from app.general import TIMEZONE_KEY, current_tz
from app.models import Setting
from app.netconfig import NetConfigError, load_netconfig, sources, update_netconfig
from app.notify.config import EMAIL, GOTIFY
from app.syncmode import load_sync_mode

router = APIRouter(prefix="/api/settings", tags=["settings"])
TIME_FORMAT_KEY = "general.time_format"


class NetworkPatch(BaseModel):
    model_config = {"extra": "forbid"}

    subnet: str | None = None
    gateway: str | None = None
    quarantine_start: str | None = None
    quarantine_end: str | None = None
    pihole_url: str | None = None
    sentinel_interface: str | None = None
    sweep_interval_s: int | None = None
    scan_window_start: str | None = None
    scan_window_end: str | None = None


class SettingsPatch(BaseModel):
    timezone: str | None = None
    time_format: Literal["24h", "12h"] | None = None
    network: NetworkPatch | None = None


def _setting(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    return row.value if row is not None else None


def _view(db: Session) -> dict[str, Any]:
    row = db.get(Setting, TIME_FORMAT_KEY)
    cfg = load_netconfig(db)
    return {
        "timezone": current_tz(db).key,
        "time_format": row.value if row is not None and row.value in ("24h", "12h") else "24h",
        "sync_mode": load_sync_mode(db),
        "network": {
            "subnet": cfg.subnet,
            "gateway": cfg.gateway,
            "quarantine_start": cfg.quarantine_start,
            "quarantine_end": cfg.quarantine_end,
            "pihole_url": cfg.pihole_url,
            "sentinel_interface": cfg.sentinel_interface,
            "sweep_interval_s": cfg.sweep_interval_s,
        },
        "scan_window": {"start": cfg.scan_window_start, "end": cfg.scan_window_end},
        "source": sources(db),
        "status": {
            "pihole_down_since": _setting(db, "pihole.down_since"),
            "dns_down_since": _setting(db, "pihole_dns.down_since"),
            "sentinel_down_since": _setting(db, "sentinel.down_since"),
            "last_sweep_at": _setting(db, "sentinel.heartbeat"),
            "maintenance_active": bool(_setting(db, "maintenance.active")),
        },
        "channels": {"gotify_url": GOTIFY.load(db)["url"], "email_sender": EMAIL.load(db)["sender"]},
    }


@router.get("")
def get_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
    return _view(db)


@router.put("")
def put_settings(body: SettingsPatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    if body.timezone is not None:
        try:
            ZoneInfo(body.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown timezone {body.timezone!r}") from exc
        db.merge(Setting(key=TIMEZONE_KEY, value=body.timezone))
    if body.time_format is not None:
        db.merge(Setting(key=TIME_FORMAT_KEY, value=body.time_format))
    if body.network is not None:
        patch = body.network.model_dump(exclude_unset=True)
        try:
            _, changes = update_netconfig(db, patch)
        except NetConfigError as exc:
            db.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        if changes:
            record_event(db, "settings.network", None, {"changes": changes})
    db.commit()
    return _view(db)
