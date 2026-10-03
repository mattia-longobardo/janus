from fastapi import APIRouter

# Routes for the Next.js server only. lib/proxy.ts never forwards /api/internal/* from the browser.
router = APIRouter(prefix="/api/internal", tags=["internal"])
