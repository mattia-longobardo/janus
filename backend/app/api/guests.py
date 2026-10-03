import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import guests
from app.api.approval import _enforce
from app.api.conflicts import commit_or_409
from app.api.devices import DeviceOut, get_device_or_404
from app.api.roles import get_dhcp
from app.db import get_db
from app.general import current_tz
from app.health import annotate
from app.models import Access, Device
from app.net.names import hostname_for
from app.providers.base import Policy
from app.providers.runtime import DhcpRef, label
from app.settingsstore import SettingsError

router = APIRouter(prefix="/api/guests", tags=["guests"])
device_router = APIRouter(prefix="/api/devices", tags=["guests"])
_RACE = "another device already uses that MAC or name: reload and try again"


class GuestOut(DeviceOut):
    guest_since: datetime | None
    guest_expires_at: datetime | None
    effective_expires_at: datetime | None = None
    expiry_source: guests.ExpirySource | None = None


class ExpiryIn(BaseModel):
    expires_at: datetime | None = None
    expires_in_hours: float | None = Field(default=None, allow_inf_nan=False, le=8760 * 10)
    expires_on: date | None = None


class GuestIn(ExpiryIn):
    mac: str
    name: str = Field(min_length=1, max_length=64)


class GuestAdmitIn(ExpiryIn):
    name: str = Field(min_length=1, max_length=64)


class GuestPatch(ExpiryIn):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    clear_expiry: bool = False


class GuestSettingsIn(BaseModel):
    auto_remove_hours: int | None = None
    inactive_remove_hours: int | None = None


def _out(db: Session, device: Device) -> GuestOut:
    out = GuestOut.model_validate(annotate(db, [device])[0])
    rules = guests.SETTINGS.load(db)
    out.effective_expires_at, out.expiry_source = guests.effective_expiry(
        device, rules["auto_remove_hours"], rules["inactive_remove_hours"])
    return out


def _require_support(dhcp: DhcpRef | None) -> None:
    if dhcp is not None and Policy.GUEST not in dhcp[1]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{label(dhcp[0])} does not support guests")


def _resolve(db: Session, body: ExpiryIn, now: datetime) -> datetime | None:
    return guests.resolve_expiry(now=now, tz=current_tz(db), expires_at=body.expires_at,
                                 expires_in_hours=body.expires_in_hours, expires_on=body.expires_on)


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


def _get_guest(db: Session, guest_id: uuid.UUID) -> Device:
    device = get_device_or_404(db, guest_id)
    if device.access is not Access.guest:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "guest not found")
    return device


@router.get("", response_model=list[GuestOut])
def list_guests(db: Session = Depends(get_db)) -> list[GuestOut]:
    rows = db.scalars(select(Device).where(Device.access == Access.guest).order_by(Device.guest_since, Device.name))
    return [_out(db, d) for d in rows]


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict[str, int | None]:
    return guests.SETTINGS.view(db)


@router.put("/settings")
def put_settings(body: GuestSettingsIn, db: Session = Depends(get_db)) -> dict[str, int | None]:
    try:
        view = guests.SETTINGS.update(db, body.model_dump(exclude_unset=True))
    except SettingsError as exc:
        raise _unprocessable(exc) from exc
    db.commit()
    return view


@router.post("", response_model=GuestOut, status_code=status.HTTP_201_CREATED)
def add_guest(body: GuestIn, db: Session = Depends(get_db), dhcp: DhcpRef | None = Depends(get_dhcp)) -> GuestOut:
    _require_support(dhcp)
    now = datetime.now(UTC)
    try:
        device = guests.add_by_mac(db, body.mac, body.name, _resolve(db, body, now), now)
    except guests.GuestError as exc:
        raise _unprocessable(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, _RACE) from exc
    commit_or_409(db, "another device already uses that MAC or name: reload and try again")
    _enforce(db, dhcp, None, None)
    return _out(db, device)


@router.patch("/{guest_id}", response_model=GuestOut)
def patch_guest(guest_id: uuid.UUID, body: GuestPatch, db: Session = Depends(get_db),
                dhcp: DhcpRef | None = Depends(get_dhcp)) -> GuestOut:
    device = _get_guest(db, guest_id)
    _require_support(dhcp)
    now = datetime.now(UTC)
    try:
        if body.clear_expiry:
            if any(v is not None for v in (body.expires_at, body.expires_in_hours, body.expires_on)):
                raise guests.GuestError("expiry: clear_expiry cannot be combined with a new expiry")
            guests.update_expiry(db, device, None)
        else:
            expires = _resolve(db, body, now)
            if expires is not None:
                guests.update_expiry(db, device, expires)
    except guests.GuestError as exc:
        raise _unprocessable(exc) from exc
    if body.name is not None and body.name != device.name:
        others = set(db.scalars(select(Device.hostname).where(Device.id != device.id)))
        device.name = body.name
        device.hostname = hostname_for(body.name, others)
    commit_or_409(db, "another device already uses that name: reload and try again")
    _enforce(db, dhcp, None, None)
    return _out(db, device)


@router.delete("/{guest_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_guest(guest_id: uuid.UUID, db: Session = Depends(get_db),
                 dhcp: DhcpRef | None = Depends(get_dhcp)) -> Response:
    device = _get_guest(db, guest_id)
    mac = device.mac
    last_ip = guests.remove(db, device, reason="removed")
    db.commit()
    _enforce(db, dhcp, mac, last_ip)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@device_router.post("/{device_id}/guest", response_model=GuestOut)
def make_guest(device_id: uuid.UUID, body: GuestAdmitIn, db: Session = Depends(get_db),
               dhcp: DhcpRef | None = Depends(get_dhcp)) -> GuestOut:
    _require_support(dhcp)
    device = get_device_or_404(db, device_id)
    if device.access is not Access.pending:
        raise _unprocessable(guests.GuestError(f"device: already a {device.access.value} device"))
    now = datetime.now(UTC)
    quarantine_ip, mac = device.last_ip, device.mac
    try:
        guests.admit(db, device, name=body.name, expires=_resolve(db, body, now), now=now)
    except guests.GuestError as exc:
        raise _unprocessable(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, _RACE) from exc
    commit_or_409(db, "another device already uses that name: reload and try again")
    _enforce(db, dhcp, mac, quarantine_ip)
    return _out(db, device)
