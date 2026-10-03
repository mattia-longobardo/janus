from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import authconfig
from app.db import get_db

router = APIRouter(prefix="/api/settings/auth", tags=["settings"])


class ProviderIn(BaseModel):
    model_config = {"extra": "forbid"}

    id: str
    name: str
    discovery_url: str
    client_id: str
    client_secret: str | None = None
    scopes: list[str]
    enabled: bool = True


class AuthIn(BaseModel):
    model_config = {"extra": "forbid"}

    allowed_emails: list[str] | None = None
    providers: list[ProviderIn] = []


def _view(cfg: authconfig.AuthConfig) -> dict[str, Any]:
    return {
        "allowed_emails": cfg.allowed_emails,
        "allowed_emails_source": cfg.allowed_emails_source,
        "providers": [
            {"id": p.id, "name": p.name, "discovery_url": p.discovery_url, "client_id": p.client_id,
             "client_secret": bool(p.client_secret), "scopes": p.scopes, "enabled": p.enabled, "source": p.source}
            for p in cfg.providers
        ],
    }


@router.get("")
def get_auth(db: Session = Depends(get_db)) -> dict[str, Any]:
    return _view(authconfig.load(db))


@router.put("")
def put_auth(body: AuthIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        cfg = authconfig.save(db, body.allowed_emails, [p.model_dump() for p in body.providers])
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _view(cfg)
