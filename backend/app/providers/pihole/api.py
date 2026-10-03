from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.netconfig import load_netconfig
from app.providers.pihole.client import shared_session
from app.providers.pihole.cutover import PiholeAdmin, preflight
from app.providers.pihole.provider import KIND, PiholeConfig

router = APIRouter(tags=["pihole"])


def current_config(db: Session) -> tuple[PiholeConfig, str | None]:
    """This Pi-hole's config and the kind holding the DHCP role. Until the per-role configuration exists, Pi-hole
    is always the DHCP provider and its URL comes from the network settings."""
    cfg = PiholeConfig(url=load_netconfig(db).pihole_url, password=settings.pihole_password,
                       lease=settings.reservation_lease)
    return cfg, KIND


@router.get("/preflight")
def pihole_preflight(db: Session = Depends(get_db)) -> dict[str, Any]:
    cfg, dhcp_kind = current_config(db)
    with PiholeAdmin(cfg.url, cfg.password, shared=shared_session(cfg.url)) as client:
        return preflight(db, client, cfg, dhcp_kind=dhcp_kind).as_dict()
