from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.providers import registry
from app.providers.base import HealthCheck, ProviderError, Role
from app.providers.config import ConfigError, config_schema, load_role, save_role, view_role

router = APIRouter(prefix="/api/providers", tags=["providers"])


class RoleBody(BaseModel):
    kind: str | None = None
    config: dict[str, Any] | None = None
    same_as: Literal["dhcp"] | None = None


@router.get("")
def list_providers(db: Session = Depends(get_db)) -> dict[str, Any]:
    available = [{
        "kind": spec.kind,
        "label": spec.label,
        "description": spec.description,
        "docs_url": spec.docs_url,
        "roles": sorted(spec.roles),
        "capabilities": sorted(spec.capabilities),
        "policies": sorted(spec.policies),
        "schema": config_schema(spec),
        "secret_fields": sorted(spec.secret_fields),
    } for spec in registry.all_specs()]
    return {"available": available, "roles": {role.value: view_role(db, role) for role in (Role.DHCP, Role.DNS)}}


@router.put("/{role}")
def put_role(role: Role, body: RoleBody, db: Session = Depends(get_db)) -> dict[str, Any] | None:
    try:
        save_role(db, role, body.kind, body.config, same_as=Role(body.same_as) if body.same_as else None)
    except ConfigError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.commit()
    return view_role(db, role)


@router.post("/{role}/test")
def test_role(role: Role, db: Session = Depends(get_db)) -> dict[str, Any]:
    rc = load_role(db, role)
    if rc is None:
        return {"ok": False, "detail": "no provider configured"}
    try:
        with rc.spec.open(rc.config) as provider:
            detail = provider.check() if isinstance(provider, HealthCheck) else f"{rc.spec.label} has no health check"
    except ProviderError as exc:
        return {"ok": False, "detail": str(exc)}
    return {"ok": True, "detail": detail}
