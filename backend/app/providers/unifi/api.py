from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.roles import get_dhcp
from app.db import get_db
from app.models import Device
from app.net.mac import normalize_mac
from app.providers.base import ProviderError
from app.providers.runtime import DhcpRef
from app.providers.unifi.provider import KIND

router = APIRouter(tags=["unifi"])


@router.get("/clients")
def list_clients(db: Session = Depends(get_db), dhcp: DhcpRef | None = Depends(get_dhcp)) -> list[dict[str, Any]]:
    """Known and connected clients with their AP or switch port, linked to the Janus device with the same MAC."""
    if dhcp is None or dhcp[0] != KIND:
        raise HTTPException(404, "UniFi does not hold the DHCP role")
    try:
        with dhcp[2]() as provider:
            rows = provider.clients()
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    device_ids = {normalize_mac(mac): str(device_id) for device_id, mac in db.execute(select(Device.id, Device.mac))}
    return [{**row, "device_id": device_ids.get(normalize_mac(row["mac"]))} for row in rows]
