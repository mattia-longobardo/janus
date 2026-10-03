from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.netconfig import load_netconfig
from app.pihole.sync import apply_sync, plan_sync
from app.providers.pihole.client import PiholeClient, PiholeError, shared_session

router = APIRouter(prefix="/api/sync", tags=["sync"])


def get_pihole(db: Session = Depends(get_db)) -> Iterator[PiholeClient]:
    url = load_netconfig(db).pihole_url
    with PiholeClient(url, settings.pihole_password, shared=shared_session(url)) as client:
        yield client


@router.get("/plan")
def sync_plan(db: Session = Depends(get_db), pihole: PiholeClient = Depends(get_pihole)) -> dict[str, Any]:
    try:
        return plan_sync(db, pihole, settings.reservation_lease).as_dict()
    except PiholeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post("/apply")
def sync_apply(db: Session = Depends(get_db), pihole: PiholeClient = Depends(get_pihole)) -> dict[str, Any]:
    try:
        diff = apply_sync(db, pihole, settings.reservation_lease)
    except PiholeError as exc:
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    db.commit()
    return diff.as_dict()
