import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from ipaddress import IPv4Address

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.conflicts import commit_or_409
from app.api.devices import DeviceOut, get_device_or_404
from app.api.groups import plan
from app.approval import ApprovalError, approve_device, block_device
from app.config import settings
from app.db import get_db
from app.models import Access, Device, Group
from app.net.ipplan import AssignmentError
from app.netconfig import load_netconfig
from app.pihole.sync import apply_sync
from app.providers.pihole.client import PiholeClient, PiholeError, shared_session
from app.syncmode import load_sync_mode

router = APIRouter(prefix="/api/devices", tags=["approval"])
PiholeFactory = Callable[[], AbstractContextManager[PiholeClient]]


def get_pihole_factory(db: Session = Depends(get_db)) -> PiholeFactory:
    url = load_netconfig(db).pihole_url
    return lambda: PiholeClient(url, settings.pihole_password, shared=shared_session(url))


class ApproveIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    group_id: int
    access: Access | None = None
    static_ip: str | None = None


class ApprovalOut(BaseModel):
    device: DeviceOut
    enforcement: str


def _enforce(db: Session, factory: PiholeFactory, revoke_ip: str | None) -> str:
    if load_sync_mode(db) != "apply":
        return "dry-run"
    try:
        with factory() as client:
            apply_sync(db, client, settings.reservation_lease)
            if revoke_ip:
                client.revoke_lease(revoke_ip)
    except PiholeError as exc:
        db.commit()
        return f"failed: {exc}"
    db.commit()
    return "applied"


def _quarantine_ip(db: Session, device: Device) -> str | None:
    try:
        return device.last_ip if device.last_ip and IPv4Address(device.last_ip) in plan(db).quarantine else None
    except ValueError:
        return None


@router.post("/{device_id}/approve", response_model=ApprovalOut)
def approve(device_id: uuid.UUID, body: ApproveIn, db: Session = Depends(get_db),
            factory: PiholeFactory = Depends(get_pihole_factory)) -> ApprovalOut:
    device = get_device_or_404(db, device_id)
    group = db.get(Group, body.group_id)
    if group is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown group")
    try:
        approve_device(db, device, plan=plan(db), name=body.name, group=group, access=body.access, static_ip=body.static_ip)
    except (ApprovalError, AssignmentError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    commit_or_409(db, "another device already holds that address, MAC or name: reload and try again")
    enforcement = _enforce(db, factory, _quarantine_ip(db, device))
    return ApprovalOut(device=DeviceOut.model_validate(device), enforcement=enforcement)


@router.post("/{device_id}/block", response_model=ApprovalOut)
def block(device_id: uuid.UUID, db: Session = Depends(get_db),
          factory: PiholeFactory = Depends(get_pihole_factory)) -> ApprovalOut:
    device = get_device_or_404(db, device_id)
    block_device(db, device)
    db.commit()
    enforcement = _enforce(db, factory, device.last_ip)
    return ApprovalOut(device=DeviceOut.model_validate(device), enforcement=enforcement)
