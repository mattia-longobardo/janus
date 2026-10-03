import logging
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from redis import Redis
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.events import record_event
from app.general import current_tz
from app.intel.identity import identity_once
from app.maintenance import Window, active_windows, load_windows
from app.metrics import start_metrics_server
from app.models import Setting
from app.netconfig import load_netconfig, load_with
from app.notify.config import build_senders
from app.notify.debounce import Debouncer, RedisDebouncer
from app.notify.dispatcher import Sender, dispatch_pending
from app.pihole.client import PiholeClient, PiholeError
from app.pihole.reservations import HostDiff
from app.pihole.sync import apply_sync, plan_sync
from app.presence import evaluate_presence, purge_sightings
from app.syncmode import load_sync_mode, load_sync_mode_with

log = logging.getLogger("janus.worker")
SessionFactory = Callable[[], AbstractContextManager[Session]]
SENTINEL_HEARTBEAT_KEY = "sentinel.heartbeat"
MAINTENANCE_KEY = "maintenance.active"


def _mark_down(db: Session, service: str, error: str) -> None:
    key = f"{service}.down_since"
    state = db.get(Setting, key)
    if state is None or state.value is None:
        db.merge(Setting(key=key, value=datetime.now(UTC).isoformat()))
        record_event(db, "infra.down", None, {"service": service, "error": error})


def _mark_up(db: Session, service: str) -> None:
    state = db.get(Setting, f"{service}.down_since")
    if state is not None and state.value is not None:
        record_event(db, "infra.up", None, {"service": service, "down_since": state.value})
        state.value = None


def reconcile_once(
    session_factory: SessionFactory,
    client_factory: Callable[[], AbstractContextManager],
    *,
    lease: str,
    apply: bool | None = None,
) -> HostDiff | None:
    with session_factory() as db:
        if apply is None:
            apply = load_sync_mode(db) == "apply"
        try:
            with client_factory() as client:
                diff = apply_sync(db, client, lease) if apply else plan_sync(db, client, lease)
        except PiholeError as exc:
            log.warning("reconcile failed: %s", exc)
            _mark_down(db, "pihole", str(exc))
            db.commit()
            return None
        _mark_up(db, "pihole")
        db.commit()
        if not diff.empty:
            log.info("reconcile %s: %s", "applied" if apply else "dry-run", diff.as_dict())
        return diff


DNS_OK_KEY = "pihole_dns.last_ok"
DNS_MAX_SILENCE = timedelta(minutes=3)


def dns_check_once(session_factory: SessionFactory, now: datetime | None = None) -> bool | None:
    """Pi-hole DNS is down when the sentinel (host network, like every LAN device) has not had an answer for
    three minutes. Before the sentinel has recorded any answer there is nothing to judge."""
    with session_factory() as db:
        now = now or datetime.now(UTC)
        row = db.get(Setting, DNS_OK_KEY)
        if row is None or not row.value:
            return None
        silence = now - datetime.fromisoformat(row.value)
        ok = silence <= DNS_MAX_SILENCE
        if ok:
            _mark_up(db, "pihole_dns")
        else:
            _mark_down(db, "pihole_dns", f"no DNS answer from Pi-hole for {int(silence.total_seconds())} s")
        db.commit()
        return ok


def check_sentinel(db: Session, now: datetime, max_age: timedelta) -> bool:
    row = db.get(Setting, SENTINEL_HEARTBEAT_KEY)
    if row is None or not row.value:
        return False
    age = now - datetime.fromisoformat(row.value)
    if age > max_age:
        _mark_down(db, "sentinel", f"no scanner heartbeat for {int(age.total_seconds())} s")
        return False
    _mark_up(db, "sentinel")
    return True


def track_maintenance(db: Session, now: datetime, windows: list[Window], tz) -> None:
    active = bool(active_windows(windows, now, tz))
    row = db.get(Setting, MAINTENANCE_KEY)
    previous = bool(row.value) if row is not None else False
    if active != previous:
        record_event(db, "maintenance.start" if active else "maintenance.end", None, {}, ts=now)
        db.merge(Setting(key=MAINTENANCE_KEY, value=active))


def presence_once(session_factory: SessionFactory, now: datetime | None = None) -> None:
    with session_factory() as db:
        now = now or datetime.now(UTC)
        windows, tz = load_windows(db), current_tz(db)
        track_maintenance(db, now, windows, tz)
        if check_sentinel(db, now, timedelta(seconds=3 * load_netconfig(db).sweep_interval_s)):
            evaluate_presence(db, now=now, timeout=timedelta(seconds=settings.presence_timeout_s), windows=windows, tz=tz)
        purge_sightings(db, now - timedelta(days=settings.sighting_retention_days))
        db.commit()


def dispatch_once(
    session_factory: SessionFactory,
    debouncer: Debouncer,
    now: datetime | None = None,
    *,
    sender_factory: Callable[[Session], dict[str, Sender]] = build_senders,
) -> int:
    with session_factory() as db:
        count = dispatch_pending(
            db, sender_factory(db), debouncer, now=now or datetime.now(UTC), tz=current_tz(db), windows=load_windows(db),
            base_url=settings.base_url, quarantine_active=load_sync_mode(db) == "apply",
        )
        db.commit()
        return count


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    heartbeat = Path(settings.heartbeat_path)
    debouncer = RedisDebouncer(Redis.from_url(settings.redis_url))
    jobs: list[tuple[str, int, Callable[[], object]]] = [
        ("reconcile", settings.reconcile_interval_s, lambda: reconcile_once(
            SessionLocal, lambda: PiholeClient(load_with(SessionLocal).pihole_url, settings.pihole_password),
            lease=settings.reservation_lease)),
        ("presence", settings.presence_interval_s, lambda: presence_once(SessionLocal)),
        ("dns", 60, lambda: dns_check_once(SessionLocal)),
        ("dispatch", settings.dispatch_interval_s, lambda: dispatch_once(SessionLocal, debouncer)),
        ("identity", settings.identity_interval_s, lambda: identity_once(SessionLocal)),
    ]
    due = {name: 0.0 for name, _, _ in jobs}
    start_metrics_server(SessionLocal)
    log.info("worker started (mode=%s)", load_sync_mode_with(SessionLocal))
    while True:
        for name, interval, job in jobs:
            if time.monotonic() >= due[name]:
                try:
                    job()
                except Exception:
                    log.exception("job %s failed", name)
                due[name] = time.monotonic() + interval
        heartbeat.touch()
        time.sleep(5)


if __name__ == "__main__":
    main()
