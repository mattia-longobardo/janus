from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.roles import get_dhcp
from app.db import get_db
from app.enforcement.sync import apply_sync, plan_sync
from app.providers.base import ProviderError
from app.providers.runtime import DhcpRef

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
