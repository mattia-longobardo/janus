from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.providers import registry
from app.providers.base import Role
from app.providers.config import load_role
from app.providers.pihole.client import shared_session
from app.providers.pihole.cutover import PiholeAdmin, preflight
from app.providers.pihole.provider import KIND, PiholeConfig

router = APIRouter(tags=["pihole"])


def current_config(db: Session) -> tuple[PiholeConfig, str | None]:
    """This Pi-hole's config (from the role it holds, DHCP first) and the kind holding the DHCP role."""
    dhcp = load_role(db, Role.DHCP)
    for rc in (dhcp, load_role(db, Role.DNS)):
        if rc is not None and rc.kind == KIND:
            return rc.config, dhcp.kind if dhcp else None
    return PiholeConfig(**registry.get_spec(KIND).env_defaults()), dhcp.kind if dhcp else None


@router.get("/preflight")
def pihole_preflight(db: Session = Depends(get_db)) -> dict[str, Any]:
    cfg, dhcp_kind = current_config(db)
    with PiholeAdmin(cfg.url, cfg.password, shared=shared_session(cfg.url)) as client:
        return preflight(db, client, cfg, dhcp_kind=dhcp_kind).as_dict()
