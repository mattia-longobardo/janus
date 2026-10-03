# Transitional: the frontend still calls /api/cutover/preflight; C5/C6 remove this module.
from fastapi import APIRouter

from app.providers.pihole.api import pihole_preflight

router = APIRouter(prefix="/api/cutover", tags=["cutover"])
router.add_api_route("/preflight", pihole_preflight, methods=["GET"])
