from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import (
    approval,
    authconfig,
    devices,
    events,
    features,
    groups,
    health,
    intel,
    internal,
    maintenance,
    map,
    notifications,
    providers,
    services,
    settings,
    sync,
)
from app.providers import registry
from app.security import require_internal


async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    detail = [{"loc": list(err.get("loc", ())), "msg": err.get("msg", "invalid"), "type": err.get("type", "")}
              for err in exc.errors()]
    return JSONResponse({"detail": detail}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def create_app() -> FastAPI:
    app = FastAPI(title="Janus")
    app.add_exception_handler(RequestValidationError, validation_error)
    app.include_router(health.router)
    protected = [Depends(require_internal)]
    for router in (groups.router, devices.router, approval.router, sync.router,
                   notifications.router, maintenance.router, events.router, intel.router, settings.router, authconfig.router,
                   map.router, services.router, features.router, providers.router, internal.router):
        app.include_router(router, dependencies=protected)
    for spec in registry.all_specs():
        if spec.router is not None:
            app.include_router(spec.router, prefix=f"/api/providers/{spec.kind}", dependencies=protected)
    return app


app = create_app()
