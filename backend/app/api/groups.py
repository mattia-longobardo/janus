import uuid
from ipaddress import IPv4Address
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.conflicts import commit_or_409
from app.db import get_db
from app.events import record_event
from app.models import Access, Device, Group
from app.net.ipplan import AssignmentError, IpRange, NetworkPlan, check_assignment, check_group_range, next_free
from app.netconfig import load_netconfig
from app.providers.runtime import infrastructure_ips

router = APIRouter(prefix="/api/groups", tags=["groups"])
GROUP_ACCESS = {Access.authorized, Access.lan_only}
REQUIRED_GROUP_FIELDS = ("name", "color", "icon", "range_start", "range_end", "default_access", "scan_enabled",
                         "scan_interval_hours")


def plan(db: Session) -> NetworkPlan:
    return load_netconfig(db).plan()


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str = Field(min_length=1, max_length=32)
    range_start: str
    range_end: str
    default_access: Access = Access.authorized
    offline_alert_hours: int | None = Field(default=None, ge=1)
    scan_enabled: bool = False
    scan_interval_hours: int = Field(default=168, ge=1, le=720)

    @field_validator("default_access")
    @classmethod
    def _group_access(cls, value: Access) -> Access:
        if value not in GROUP_ACCESS:
            raise ValueError("default_access must be authorized or lan_only")
        return value


class GroupPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str | None = Field(default=None, min_length=1, max_length=32)
    range_start: str | None = None
    range_end: str | None = None
    default_access: Access | None = None
    offline_alert_hours: int | None = Field(default=None, ge=1)
    scan_enabled: bool | None = None
    scan_interval_hours: int | None = Field(default=None, ge=1, le=720)

    @field_validator("default_access")
    @classmethod
    def _group_access(cls, value: Access | None) -> Access | None:
        if value is not None and value not in GROUP_ACCESS:
            raise ValueError("default_access must be authorized or lan_only")
        return value

    @model_validator(mode="after")
    def _no_null_required(self) -> "GroupPatch":
        for name in REQUIRED_GROUP_FIELDS:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class GroupOut(BaseModel):
    id: int
    name: str
    color: str
    icon: str
    range_start: str
    range_end: str
    default_access: Access
    offline_alert_hours: int | None
    device_count: int
    scan_enabled: bool
    scan_interval_hours: int


def _out(db: Session, group: Group) -> GroupOut:
    count = db.scalar(select(func.count()).select_from(Device).where(Device.group_id == group.id)) or 0
    return GroupOut(
        id=group.id, name=group.name, color=group.color, icon=group.icon,
        range_start=group.range_start, range_end=group.range_end, default_access=group.default_access,
        offline_alert_hours=group.offline_alert_hours, device_count=count,
        scan_enabled=group.scan_enabled, scan_interval_hours=group.scan_interval_hours,
    )


def _validated_range(db: Session, start: str, end: str, exclude_id: int | None) -> IpRange:
    try:
        rng = IpRange.parse(start, end)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    others = [g.ip_range() for g in db.scalars(select(Group)) if g.id != exclude_id]
    try:
        check_group_range(plan(db), rng, others)
    except AssignmentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return rng


def _get(db: Session, group_id: int) -> Group:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "group not found")
    return group


def _name_taken(db: Session, name: str, exclude_id: int | None) -> bool:
    existing = db.scalar(select(Group).where(Group.name == name))
    return existing is not None and existing.id != exclude_id


@router.get("", response_model=list[GroupOut])
def list_groups(db: Session = Depends(get_db)) -> list[GroupOut]:
    groups = db.scalars(select(Group).order_by(Group.range_start))
    return sorted((_out(db, g) for g in groups), key=lambda g: IPv4Address(g.range_start))


@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(body: GroupIn, db: Session = Depends(get_db)) -> GroupOut:
    if _name_taken(db, body.name, None):
        raise HTTPException(status.HTTP_409_CONFLICT, f"a group named {body.name!r} already exists")
    rng = _validated_range(db, body.range_start, body.range_end, None)
    group = Group(
        name=body.name, color=body.color, icon=body.icon, range_start=str(rng.start), range_end=str(rng.end),
        default_access=body.default_access, offline_alert_hours=body.offline_alert_hours,
        scan_enabled=body.scan_enabled, scan_interval_hours=body.scan_interval_hours,
    )
    db.add(group)
    commit_or_409(db, f"a group named {body.name!r} or with that range already exists")
    return _out(db, group)


@router.patch("/{group_id}", response_model=GroupOut)
def update_group(group_id: int, body: GroupPatch, db: Session = Depends(get_db)) -> GroupOut:
    group = _get(db, group_id)
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields and _name_taken(db, fields["name"], group.id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"a group named {fields['name']!r} already exists")
    if "range_start" in fields or "range_end" in fields:
        rng = _validated_range(db, fields.get("range_start", group.range_start),
                               fields.get("range_end", group.range_end), group.id)
        outside = sorted(
            d.static_ip for d in group.devices if d.static_ip and IPv4Address(d.static_ip) not in rng
        )
        if outside:
            raise HTTPException(status.HTTP_409_CONFLICT, f"devices would fall outside the range: {', '.join(outside)}")
        fields["range_start"], fields["range_end"] = str(rng.start), str(rng.end)
    for key, value in fields.items():
        setattr(group, key, value)
    commit_or_409(db, "another group already uses that name")
    return _out(db, group)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: int, db: Session = Depends(get_db)) -> Response:
    group = _get(db, group_id)
    if group.devices:
        raise HTTPException(status.HTTP_409_CONFLICT, f"group still has {len(group.devices)} devices")
    db.delete(group)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{group_id}/next-free-ip")
def next_free_ip(group_id: int, device_id: uuid.UUID | None = None, db: Session = Depends(get_db)) -> dict[str, str | None]:
    group = _get(db, group_id)
    query = select(Device.static_ip).where(Device.static_ip.is_not(None))
    if device_id is not None:
        query = query.where(Device.id != device_id)
    taken = {IPv4Address(ip) for ip in db.scalars(query)}
    free = next_free(plan(db), group.ip_range(), taken)
    return {"ip": str(free) if free else None}


def _pinned_ips(db: Session) -> set[str]:
    return {load_netconfig(db).gateway} | infrastructure_ips(db)


@router.post("/{group_id}/compact")
def compact_group(group_id: int, dry_run: bool = True, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Renumber the group's devices from the start of its range, keeping their order and closing gaps."""
    group = _get(db, group_id)
    network = plan(db)
    pinned_ips = _pinned_ips(db)
    members = sorted(
        db.scalars(select(Device).where(Device.group_id == group.id, Device.static_ip.is_not(None))),
        key=lambda d: IPv4Address(d.static_ip),
    )
    movable = [d for d in members if d.static_ip not in pinned_ips]
    member_ids = {d.id for d in movable}
    blocked = {
        IPv4Address(ip)
        for ip in db.scalars(select(Device.static_ip).where(Device.static_ip.is_not(None)))
        if ip
    } - {IPv4Address(d.static_ip) for d in movable}
    blocked |= {IPv4Address(ip) for ip in pinned_ips if ip}
    targets: list[IPv4Address] = []
    for addr in group.ip_range():
        if len(targets) == len(movable):
            break
        try:
            targets.append(check_assignment(network, str(addr), group.ip_range(), blocked))
        except AssignmentError:
            continue
    moves = [
        {"device_id": str(d.id), "name": d.name, "from": d.static_ip, "to": str(ip)}
        for d, ip in zip(movable, targets, strict=False)
        if d.static_ip != str(ip)
    ]
    pinned = [{"name": d.name, "ip": d.static_ip} for d in members if d.id not in member_ids]
    if not dry_run and moves:
        by_id = {str(d.id): d for d in movable}
        for move in moves:
            by_id[move["device_id"]].static_ip = None
        db.flush()
        for move in moves:
            by_id[move["device_id"]].static_ip = move["to"]
        record_event(db, "group.compacted", None, {"group": group.name, "moves": moves})
        commit_or_409(db, "another change touched these addresses, try again")
    return {"group": group.name, "dry_run": dry_run, "moves": moves, "unchanged": len(members) - len(moves),
            "pinned": pinned}
