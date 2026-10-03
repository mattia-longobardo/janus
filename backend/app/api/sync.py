from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.roles import get_dhcp
from app.db import get_db
from app.enforcement.sync import apply_sync, plan_sync
from app.providers.base import ProviderError
from app.providers.runtime import DhcpRef, record_dhcp_identity
from app.syncmode import SyncMode, set_sync_mode

router = APIRouter(prefix="/api/sync", tags=["sync"])


def _require(dhcp: DhcpRef | None) -> DhcpRef:
    if dhcp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no DHCP provider with reservations")
    return dhcp


@router.get("/plan")
def sync_plan(db: Session = Depends(get_db), dhcp: DhcpRef | None = Depends(get_dhcp)) -> dict[str, Any]:
    kind, policies, factory = _require(dhcp)
    try:
        with factory() as store:
            return plan_sync(db, store, kind, policies).as_dict(store.describe)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post("/apply")
def sync_apply(db: Session = Depends(get_db), dhcp: DhcpRef | None = Depends(get_dhcp)) -> dict[str, Any]:
    kind, policies, factory = _require(dhcp)
    try:
        with factory() as store:
            diff = apply_sync(db, store, kind, policies)
    except ProviderError as exc:
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    db.commit()
    return diff.as_dict(store.describe)


class ModeIn(BaseModel):
    mode: SyncMode


@router.post("/mode")
def sync_mode(body: ModeIn, db: Session = Depends(get_db),
              dhcp: DhcpRef | None = Depends(get_dhcp)) -> dict[str, Any]:
    """Provider-neutral enforcement switch; the UI shows it to admins only (the API trusts the internal token)."""
    if body.mode == "apply" and dhcp is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no DHCP provider with reservations: cannot enforce")
    if body.mode == "apply":
        record_dhcp_identity(db, dhcp[0])   # the reviewed box: the worker must not undo this switch
    set_sync_mode(db, body.mode, actor="web")
    db.commit()
    return {"mode": body.mode}
