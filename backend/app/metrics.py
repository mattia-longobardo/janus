import logging
import threading
from collections.abc import Callable
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.health import annotate
from app.models import Access, Device, Event, Setting
from app.providers.base import Role
from app.providers.config import load_role
from app.syncmode import load_sync_mode

log = logging.getLogger("janus.metrics")
_started = threading.Lock()
_server: ThreadingHTTPServer | None = None


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class _Family:
    def __init__(self, name: str, kind: str, doc: str) -> None:
        self.name, self.kind, self.doc = f"janus_{name}", kind, doc
        self.samples: list[tuple[dict[str, str], float]] = []

    def add(self, value: float, **labels: str) -> None:
        self.samples.append((labels, float(value)))

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.doc}", f"# TYPE {self.name} {self.kind}"]
        for labels, value in self.samples:
            label_text = ",".join(f'{k}="{_escape(v)}"' for k, v in sorted(labels.items()))
            lines.append(f"{self.name}{{{label_text}}} {value:g}" if label_text else f"{self.name} {value:g}")
        return "\n".join(lines)


def _setting(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    return row.value if row is not None else None


def _timestamp(value: Any) -> float | None:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return None
    return None


def render_metrics(db: Session) -> str:
    families: list[_Family] = []

    devices = list(db.scalars(select(Device)))
    by_state = _Family("devices", "gauge", "Known devices by access and presence.")
    counts: dict[tuple[str, str], int] = {(a.value, o): 0 for a in Access for o in ("true", "false")}
    for d in devices:
        counts[(d.access.value, "true" if d.online else "false")] += 1
    for (access, online), n in sorted(counts.items()):
        by_state.add(n, access=access, online=online)
    families.append(by_state)

    pending = _Family("devices_pending", "gauge", "Devices waiting for approval.")
    pending.add(sum(1 for d in devices if d.access is Access.pending))
    families.append(pending)

    health = _Family("devices_health", "gauge", "Devices by health (unmuted risks, wrong IP, conflicts).")
    levels = {"ok": 0, "warning": 0, "critical": 0}
    for d in annotate(db, devices):
        levels[d.health] = levels.get(d.health, 0) + 1
    for level, n in levels.items():
        health.add(n, health=level)
    families.append(health)

    sweep = _Family("last_sweep_timestamp_seconds", "gauge", "Unix time of the sentinel's last ARP sweep.")
    sweep_ts = _timestamp(_setting(db, "sentinel.heartbeat"))
    if sweep_ts is not None:
        sweep.add(sweep_ts)
    families.append(sweep)

    scan = _Family("last_port_scan_timestamp_seconds", "gauge", "Unix time of the most recent port scan.")
    scan_ts = _timestamp(db.scalar(select(func.max(Device.last_scan_at))))
    if scan_ts is not None:
        scan.add(scan_ts)
    families.append(scan)

    provider = _Family("provider_up", "gauge", "1 when the provider holding the role answers, 0 while it is marked down.")
    for role in (Role.DHCP, Role.DNS):
        if load_role(db, role) is not None:   # a role that is off has no provider to be up or down
            provider.add(0 if _setting(db, f"{role.value}.down_since") else 1, role=role.value)
    families.append(provider)

    sentinel = _Family("sentinel_up", "gauge", "1 when the sentinel heartbeat is fresh, 0 while it is marked down.")
    sentinel.add(0 if _setting(db, "sentinel.down_since") else 1)
    families.append(sentinel)

    maintenance = _Family("maintenance_active", "gauge", "1 while a maintenance window is running.")
    maintenance.add(1 if _setting(db, "maintenance.active") else 0)
    families.append(maintenance)

    mode = _Family("sync_mode_info", "gauge", "Reservation sync mode (dry-run or apply).")
    mode.add(1, mode=load_sync_mode(db))
    families.append(mode)

    events = _Family("events_total", "counter", "Events recorded by Janus, by type.")
    for kind, n in db.execute(select(Event.type, func.count()).group_by(Event.type).order_by(Event.type)):
        events.add(n, type=kind)
    families.append(events)

    return "\n".join(f.render() for f in families) + "\n"


def _handler(session_factory: Callable[[], Any]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?")[0] != "/metrics":
                self.send_error(404)
                return
            try:
                with session_factory() as db:
                    body = render_metrics(db).encode()
            except Exception:
                log.exception("metrics scrape failed")
                self.send_error(500)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            return

    return Handler


def start_metrics_server(session_factory: Callable[[], Any], port: int = 9108) -> ThreadingHTTPServer | None:
    """Serve /metrics on a daemon thread; calling it again is a no-op."""
    global _server
    with _started:
        if _server is not None:
            return _server
        try:
            server = ThreadingHTTPServer(("0.0.0.0", port), _handler(session_factory))
        except OSError:
            log.exception("metrics server could not bind port %s", port)
            return None
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, name="janus-metrics", daemon=True).start()
        log.info("metrics on :%s/metrics", port)
        _server = server
        return server
