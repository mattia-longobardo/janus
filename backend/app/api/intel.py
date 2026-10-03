import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.devices import get_device_or_404
from app.api.sync import get_pihole
from app.db import get_db
from app.general import current_tz
from app.intel.dns import analyze
from app.intel.rules import summarize
from app.intel.scanning import on_lan
from app.models import DeviceFact, Service
from app.netconfig import load_netconfig
from app.providers.base import DnsQuery
from app.providers.pihole.client import PiholeClient, PiholeError
from app.providers.pihole.dns import normalize

router = APIRouter(prefix="/api/devices", tags=["intelligence"])


@router.get("/{device_id}/facts")
def device_facts(device_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    device = get_device_or_404(db, device_id)
    rows = list(db.scalars(select(DeviceFact).where(DeviceFact.mac == device.mac))) if device.mac else []
    return {
        "summary": summarize(rows),
        "facts": [{"field": r.field, "value": r.value, "source": r.source, "confidence": r.confidence,
                   "observed_at": r.observed_at.isoformat()} for r in sorted(rows, key=lambda r: (r.field, -r.confidence))],
    }


@router.get("/{device_id}/services")
def device_services(device_id: uuid.UUID, all: bool = False, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    device = get_device_or_404(db, device_id)
    query = select(Service).where(Service.mac == device.mac).order_by(Service.port)
    if not all:
        query = query.where(Service.state == "open")
    return [{"port": s.port, "proto": s.proto, "state": s.state, "service": s.service, "version": s.version,
             "risk": s.risk, "risk_reason": s.risk_reason, "muted": s.muted, "first_seen": s.first_seen.isoformat(),
             "last_seen": s.last_seen.isoformat()} for s in db.scalars(query)]


@router.post("/{device_id}/scan", status_code=status.HTTP_202_ACCEPTED)
def request_scan(device_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, bool]:
    device = get_device_or_404(db, device_id)
    if not device.last_ip:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the device has no known IP address yet")
    if not on_lan(device.last_ip, load_netconfig(db).subnet):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{device.last_ip} is not on the home network")
    device.scan_requested_at = datetime.now(UTC)
    db.commit()
    return {"queued": True}


def _device_queries(db: Session, pihole: PiholeClient, device_id: uuid.UUID,
                    hours: int) -> tuple[list[DnsQuery], int, int]:
    device = get_device_or_404(db, device_id)
    if not device.last_ip:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the device has no known IP address yet")
    until = int(time.time())
    try:
        queries, total = pihole.list_queries(device.last_ip, until - hours * 3600, until, disk=hours > 24)
    except PiholeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return [normalize(q) for q in queries], total, until


@router.get("/{device_id}/dns")
def device_dns(device_id: uuid.UUID, hours: int = Query(default=24, ge=1, le=168), db: Session = Depends(get_db),
               pihole: PiholeClient = Depends(get_pihole)) -> dict[str, Any]:
    queries, total, _ = _device_queries(db, pihole, device_id, hours)
    counts = Counter(q.domain for q in queries)
    blocked_domains = {q.domain for q in queries if q.blocked}
    return {
        "total": total,
        "sampled": len(queries),
        "truncated": total > len(queries),
        "blocked": sum(1 for q in queries if q.blocked),
        "domains": [{"domain": d, "count": n, "blocked": d in blocked_domains} for d, n in counts.most_common(20)],
    }


@router.get("/{device_id}/dns/analysis")
def device_dns_analysis(device_id: uuid.UUID, hours: int = Query(default=24, ge=1, le=168),
                        db: Session = Depends(get_db), pihole: PiholeClient = Depends(get_pihole)) -> dict[str, Any]:
    queries, total, until = _device_queries(db, pihole, device_id, hours)
    return analyze(queries, total, until - hours * 3600, until, hours, current_tz(db))
