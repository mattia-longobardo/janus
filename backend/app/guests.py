"""Guest devices: saved by MAC, no fixed IP, optionally expiring (own expiry, or global rules)."""
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events import record_event
from app.models import Access, Device
from app.net.mac import is_private_mac, normalize_mac
from app.net.names import hostname_for
from app.settingsstore import OverlayStore, SettingsError, StoreField

ExpirySource = Literal["device", "global", "inactive"]
MAX_HOURS = 8760


class GuestError(ValueError):
    pass


def _hours(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_HOURS:
        raise SettingsError(f"hours must be a whole number between 1 and {MAX_HOURS}")
    return value


def _color(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        raise SettingsError("color must be a hex colour like #4FC3D9")
    return value


def _icon(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 32:
        raise SettingsError("icon must be 1 to 32 characters")
    return value


# None = rule off. auto counts from guest_since, inactive from last_seen (or guest_since if never seen).
# color/icon style guests like a group; the defaults are the look guests always had.
SETTINGS = OverlayStore("guests.settings", [
    StoreField("auto_remove_hours", lambda: None, validate=_hours),
    StoreField("inactive_remove_hours", lambda: None, validate=_hours),
    StoreField("color", lambda: "#4FC3D9", validate=_color),
    StoreField("icon", lambda: "guest", validate=_icon),
])


def look(db: Session) -> dict[str, str]:
    """The guests' colour and icon; a stored value that no longer passes validation falls back to the default."""
    stored = SETTINGS.load(db)
    out = {}
    for name, check in (("color", _color), ("icon", _icon)):
        try:
            out[name] = check(stored[name])
        except SettingsError:
            out[name] = SETTINGS.fields[name].default()
    return out


def resolve_expiry(*, now: datetime, tz: ZoneInfo, expires_at: datetime | None = None,
                   expires_in_hours: float | None = None, expires_on: date | None = None) -> datetime | None:
    if sum(v is not None for v in (expires_at, expires_in_hours, expires_on)) > 1:
        raise GuestError("expiry: only one of expires_at, expires_in_hours, expires_on")
    if expires_at is not None:
        # A naive value is read as local time.
        when = (expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=tz)).astimezone(UTC)
    elif expires_in_hours is not None:
        try:
            when = now + timedelta(hours=expires_in_hours)
        except (OverflowError, ValueError) as exc:
            raise GuestError("expiry: out of range") from exc
    elif expires_on is not None:
        when = datetime.combine(expires_on, time(23, 59, 59), tz).astimezone(UTC)
    else:
        return None
    if when <= now:
        raise GuestError("expiry: must be in the future")
    return when


def effective_expiry(device: Device, auto_remove_hours: int | None,
                     inactive_remove_hours: int | None) -> tuple[datetime | None, ExpirySource | None]:
    if device.guest_expires_at is not None:
        return device.guest_expires_at, "device"
    candidates: list[tuple[datetime, ExpirySource]] = []
    if auto_remove_hours is not None and device.guest_since is not None:
        candidates.append((device.guest_since + timedelta(hours=auto_remove_hours), "global"))
    if inactive_remove_hours is not None:
        # Activity from before the device was admitted does not count.
        seen = [t for t in (device.last_seen, device.guest_since) if t is not None]
        if seen:
            last = max(seen)
            candidates.append((last + timedelta(hours=inactive_remove_hours), "inactive"))
    if not candidates:
        return None, None
    return min(candidates, key=lambda c: c[0])


def admit(db: Session, device: Device, *, name: str, expires: datetime | None, now: datetime) -> Device:
    if device.mac is None:
        raise GuestError("mac: a device without a MAC cannot be a guest")
    others = set(db.scalars(select(Device.hostname).where(Device.id != device.id)))
    device.name = name
    device.hostname = hostname_for(name, others)
    device.access = Access.guest
    device.static_ip = None
    device.group = None
    device.guest_since = now
    device.guest_expires_at = expires
    db.flush()
    record_event(db, "guest.added", device.mac, {
        "device_id": str(device.id), "name": name, "mac": device.mac,
        "expires_at": expires.isoformat() if expires else None,
    })
    return device


def add_by_mac(db: Session, mac: str, name: str, expires: datetime | None, now: datetime) -> Device:
    try:
        mac = normalize_mac(mac)
    except ValueError as exc:
        raise GuestError(f"mac: {exc}") from exc
    device = db.scalar(select(Device).where(Device.mac == mac))
    if device is None:
        device = Device(mac=mac, name=name, hostname="", access=Access.pending, private_mac=is_private_mac(mac))
        db.add(device)
    elif device.access is not Access.pending:
        raise GuestError(f"mac: already a {device.access.value} device")
    return admit(db, device, name=name, expires=expires, now=now)


def update_expiry(db: Session, device: Device, expires: datetime | None) -> Device:
    device.guest_expires_at = expires
    db.flush()
    return device


def remove(db: Session, device: Device, *, reason: Literal["removed", "expired"]) -> str | None:
    last_ip = device.last_ip
    record_event(db, f"guest.{reason}", device.mac, {"name": device.name, "mac": device.mac, "last_ip": last_ip})
    db.delete(device)
    db.flush()
    return last_ip


def expired(db: Session, now: datetime) -> list[Device]:
    rules = SETTINGS.load(db)
    due = []
    for device in db.scalars(select(Device).where(Device.access == Access.guest).order_by(Device.guest_since)):
        when, _ = effective_expiry(device, rules["auto_remove_hours"], rules["inactive_remove_hours"])
        if when is not None and when <= now:
            due.append(device)
    return due
