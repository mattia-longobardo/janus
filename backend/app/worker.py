import logging
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from redis import Redis
from sqlalchemy.orm import Session

from app import guests
from app.config import settings
from app.db import SessionLocal
from app.enforcement.reservations import ReservationDiff
from app.enforcement.sync import apply_sync, plan_sync
from app.events import record_event
from app.general import current_tz
from app.intel.identity import identity_once
from app.maintenance import Window, active_windows, load_windows
from app.metrics import start_metrics_server
from app.models import Setting
from app.netconfig import load_netconfig
from app.notify.config import build_senders
from app.notify.debounce import Debouncer, RedisDebouncer
from app.notify.dispatcher import Sender, dispatch_pending
from app.presence import evaluate_presence, purge_sightings
from app.providers.base import Capability, LeaseControl, ProviderError, Role, role_capabilities
from app.providers.config import load_role
from app.providers.runtime import DhcpRef, dhcp_identity, label, record_dhcp_identity, reservation_provider
from app.syncmode import load_sync_mode, load_sync_mode_with, set_sync_mode

log = logging.getLogger("janus.worker")
SessionFactory = Callable[[], AbstractContextManager[Session]]
SENTINEL_HEARTBEAT_KEY = "sentinel.heartbeat"
MAINTENANCE_KEY = "maintenance.active"


def _with_provider(payload: dict, provider: str | None) -> dict:
    return {**payload, "provider": provider} if provider else payload


def _mark_down(db: Session, service: str, error: str, *, provider: str | None = None) -> None:
    key = f"{service}.down_since"
    state = db.get(Setting, key)
    if state is None or state.value is None:
        db.merge(Setting(key=key, value=datetime.now(UTC).isoformat()))
        record_event(db, "infra.down", None, _with_provider({"service": service, "error": error}, provider))


def _mark_up(db: Session, service: str, *, provider: str | None = None) -> None:
    state = db.get(Setting, f"{service}.down_since")
    if state is not None and state.value is not None:
        record_event(db, "infra.up", None, _with_provider({"service": service, "down_since": state.value}, provider))
        state.value = None


def _clear_down(db: Session, service: str) -> None:
    """Forget an outage without announcing a recovery: the role was turned off, nothing came back."""
    state = db.get(Setting, f"{service}.down_since")
    if state is not None and state.value is not None:
        state.value = None


def dhcp_for(db: Session) -> DhcpRef | None:
    return reservation_provider(db)


def reconcile_once(
    session_factory: SessionFactory,
    factory_for: Callable[[Session], DhcpRef | None],
    *,
    apply: bool | None = None,
) -> ReservationDiff | None:
    """Bring the DHCP provider's reservations in line with Janus. Without a provider that takes reservations there
    is nothing to do, and an outage left open from before is dropped silently."""
    with session_factory() as db:
        try:
            dhcp = factory_for(db)
        except Exception as exc:
            # A config that cannot even be resolved: report it like an outage instead of killing the job loop.
            log.exception("reading the DHCP provider configuration failed")
            _mark_down(db, Role.DHCP.value, f"provider configuration error: {exc}")
            db.commit()
            return None
        if dhcp is None:
            _clear_down(db, Role.DHCP.value)
            db.commit()
            return None
        kind, policies, factory = dhcp
        provider = label(kind)
        if record_dhcp_identity(db, kind):
            # D9 also for env changes: a different DHCP box is never written to before a review.
            log.warning("DHCP provider changed to %s: switching to dry-run", dhcp_identity(db, kind))
            set_sync_mode(db, "dry-run", actor="system")
            apply = False
        if apply is None:
            apply = load_sync_mode(db) == "apply"
        try:
            with factory() as store:
                diff = apply_sync(db, store, kind, policies) if apply else plan_sync(db, store, kind, policies)
        except ProviderError as exc:
            log.warning("reconcile failed: %s", exc)
            _mark_down(db, Role.DHCP.value, str(exc), provider=provider)
            db.commit()
            return None
        _mark_up(db, Role.DHCP.value, provider=provider)
        db.commit()
        if not diff.empty:
            log.info("reconcile %s: %s", "applied" if apply else "dry-run", diff.as_dict(store.describe))
        return diff


def guests_once(session_factory: SessionFactory, factory_for: Callable[[Session], DhcpRef | None],
                now: datetime | None = None) -> int:
    """Remove the guests whose time is up. The removals are committed before the provider is contacted; in apply
    mode the provider then drops their rows and revokes their leases. A provider error is left to the next
    reconcile: the guests are gone from Janus either way."""
    with session_factory() as db:
        due = guests.expired(db, now or datetime.now(UTC))
        removed = [(device.mac, guests.remove(db, device, reason="expired")) for device in due]
        db.commit()
        if not removed:
            return 0
        try:
            dhcp = factory_for(db)
            if dhcp is None or load_sync_mode(db) != "apply":
                return len(removed)
            kind, policies, factory = dhcp
            with factory() as store:
                apply_sync(db, store, kind, policies)
                if isinstance(store, LeaseControl):
                    for mac, last_ip in removed:
                        store.force_renew(mac, last_ip)
        except ProviderError as exc:
            log.warning("removing expired guests from the DHCP provider failed, the next reconcile retries: %s", exc)
        db.commit()
        return len(removed)


DNS_OK_KEY = "dns.last_ok"
DNS_MAX_SILENCE = timedelta(minutes=3)


def dns_check_once(session_factory: SessionFactory, now: datetime | None = None) -> bool | None:
    """DNS is down when the sentinel (host network, like every LAN device) has not had an answer for three
    minutes. Before the sentinel has recorded any answer there is nothing to judge, and a DNS provider that cannot
    be probed is never judged (an outage left open from before is dropped silently)."""
    with session_factory() as db:
        rc = load_role(db, Role.DNS)
        if rc is None or Capability.DNS_PROBE not in role_capabilities(rc.spec, Role.DNS):
            _clear_down(db, Role.DNS.value)
            db.commit()
            return None
        now = now or datetime.now(UTC)
        row = db.get(Setting, DNS_OK_KEY)
        if row is None or not row.value:
            return None
        silence = now - datetime.fromisoformat(row.value)
        ok = silence <= DNS_MAX_SILENCE
        if ok:
            _mark_up(db, Role.DNS.value, provider=rc.spec.label)
        else:
            _mark_down(db, Role.DNS.value, f"no DNS answer from {rc.spec.label} for {int(silence.total_seconds())} s",
                       provider=rc.spec.label)
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
        ("reconcile", settings.reconcile_interval_s, lambda: reconcile_once(SessionLocal, dhcp_for)),
        ("presence", settings.presence_interval_s, lambda: presence_once(SessionLocal)),
        ("dns", 60, lambda: dns_check_once(SessionLocal)),
        ("dispatch", settings.dispatch_interval_s, lambda: dispatch_once(SessionLocal, debouncer)),
        ("identity", settings.identity_interval_s, lambda: identity_once(SessionLocal)),
        ("guests", settings.guests_interval_s, lambda: guests_once(SessionLocal, dhcp_for)),
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
