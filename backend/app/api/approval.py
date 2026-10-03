import uuid
from ipaddress import IPv4Address

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.conflicts import commit_or_409
from app.api.devices import DeviceOut, get_device_or_404
from app.api.groups import plan
from app.api.roles import get_dhcp
from app.approval import ApprovalError, approve_device, block_device
from app.db import get_db
from app.enforcement.sync import apply_sync
from app.models import Access, Device, Group
from app.net.ipplan import AssignmentError
from app.providers.base import LeaseControl, Policy, ProviderError
from app.providers.runtime import DhcpRef, label
from app.syncmode import load_sync_mode

router = APIRouter(prefix="/api/devices", tags=["approval"])
POLICY_OF: dict[Access, Policy] = {Access.authorized: Policy.FULL, Access.lan_only: Policy.LAN_ONLY}


class ApproveIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    group_id: int
    access: Access | None = None
    static_ip: str | None = None


class ApprovalOut(BaseModel):
    device: DeviceOut
    enforcement: str


def _enforce(db: Session, dhcp: DhcpRef | None, revoke_mac: str | None, revoke_ip: str | None) -> str:
    """Sync the reservations now, then make the device renew its lease (when `revoke_mac` is given)."""
    if dhcp is None:
        return "no provider"
    if load_sync_mode(db) != "apply":
        return "dry-run"
    kind, policies, factory = dhcp
    try:
        with factory() as store:
            apply_sync(db, store, kind, policies)
            if revoke_mac and isinstance(store, LeaseControl):
                store.force_renew(revoke_mac, revoke_ip)
    except ProviderError as exc:
        db.commit()
        return f"failed: {exc}"
    db.commit()
    return "applied"


def _check_policy(dhcp: DhcpRef | None, access: Access) -> None:
    policy = POLICY_OF.get(access)
    if dhcp is not None and policy is not None and policy not in dhcp[1]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{label(dhcp[0])} does not support {policy}")


def _quarantine_ip(db: Session, device: Device) -> str | None:
    try:
        return device.last_ip if device.last_ip and IPv4Address(device.last_ip) in plan(db).quarantine else None
    except ValueError:
        return None


@router.post("/{device_id}/approve", response_model=ApprovalOut)
def approve(device_id: uuid.UUID, body: ApproveIn, db: Session = Depends(get_db),
            dhcp: DhcpRef | None = Depends(get_dhcp)) -> ApprovalOut:
    device = get_device_or_404(db, device_id)
    group = db.get(Group, body.group_id)
    if group is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown group")
    _check_policy(dhcp, body.access or group.default_access)
    try:
        approve_device(db, device, plan=plan(db), name=body.name, group=group, access=body.access, static_ip=body.static_ip)
    except (ApprovalError, AssignmentError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    commit_or_409(db, "another device already holds that address, MAC or name: reload and try again")
    quarantine_ip = _quarantine_ip(db, device)
    enforcement = _enforce(db, dhcp, device.mac if quarantine_ip else None, quarantine_ip)
    return ApprovalOut(device=DeviceOut.model_validate(device), enforcement=enforcement)


@router.post("/{device_id}/block", response_model=ApprovalOut)
def block(device_id: uuid.UUID, db: Session = Depends(get_db),
          dhcp: DhcpRef | None = Depends(get_dhcp)) -> ApprovalOut:
    device = get_device_or_404(db, device_id)
    block_device(db, device)
    db.commit()
    enforcement = _enforce(db, dhcp, device.mac, device.last_ip)
    return ApprovalOut(device=DeviceOut.model_validate(device), enforcement=enforcement)
