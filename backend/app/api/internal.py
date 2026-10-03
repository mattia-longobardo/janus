from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import authconfig
from app.db import get_db

# Routes for the Next.js server only. lib/proxy.ts never forwards /api/internal/* from the browser.
router = APIRouter(prefix="/api/internal", tags=["internal"])


@router.get("/auth-config")
def auth_config(db: Session = Depends(get_db)) -> dict[str, Any]:
    return authconfig.internal_view(authconfig.load(db))
