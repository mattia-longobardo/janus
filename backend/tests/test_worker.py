from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.config import settings
from app.events import record_event
from app.models import Access, Device, Event, Group, NotificationRule, Setting, Sighting
from app.notify.debounce import MemoryDebouncer
from app.notify.store import default_rule_rows
from app.providers.base import Policy
from app.providers.pihole import SPEC
from app.providers.pihole.provider import PiholeConfig, PiholeProvider
from app.worker import dhcp_for, dispatch_once, presence_once, reconcile_once
from tests.fakes import FakePihole
from tests.fakes_provider import FakeStore

CFG = PiholeConfig(url="http://192.168.1.220:1000", password="pw", lease="24h")


def _seed(db):
    g = Group(name="People", color="#6FB7FF", icon="device", range_start="192.168.1.10",
              range_end="192.168.1.19", default_access=Access.authorized)
    db.add(g)
    db.flush()
    db.add(Device(mac="00:00:5E:00:53:10", name="LAPTOP_A", hostname="laptop-a", group=g,
                  static_ip="192.168.1.10", access=Access.authorized))
    db.flush()


def _count(db, kind):
    return db.scalar(select(func.count()).select_from(Event).where(Event.type == kind))


def _pihole(fake):
    return lambda _db: ("pihole", SPEC.policies, lambda: PiholeProvider(fake, CFG))


def test_reconcile_dry_run_never_writes(db):
    _seed(db)
    fake = FakePihole()
    diff = reconcile_once(lambda: nullcontext(db), _pihole(fake), apply=False)
    assert [r.mac for r in diff.to_add] == ["00:00:5E:00:53:10"]
    assert fake.writes == []


def test_reconcile_apply_writes(db):
    _seed(db)
    fake = FakePihole()
    reconcile_once(lambda: nullcontext(db), _pihole(fake), apply=True)
    assert fake.hosts == ["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"]


def test_reconcile_records_single_outage(db):
    _seed(db)
    down = FakePihole(fail=True)
    assert reconcile_once(lambda: nullcontext(db), _pihole(down), apply=True) is None
    assert reconcile_once(lambda: nullcontext(db), _pihole(down), apply=True) is None
    assert _count(db, "infra.down") == 1
    reconcile_once(lambda: nullcontext(db), _pihole(FakePihole()), apply=True)
    assert _count(db, "infra.up") == 1
    reconcile_once(lambda: nullcontext(db), _pihole(FakePihole()), apply=True)
    assert _count(db, "infra.up") == 1
    up = db.scalars(select(Event).where(Event.type == "infra.up")).one()
    assert up.payload["service"] == "dhcp" and up.payload["provider"] == "Pi-hole"


def test_reconcile_line_rejection_is_not_an_outage(db):
    _seed(db)
    fake = FakePihole(reject={"00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"})
    diff = reconcile_once(lambda: nullcontext(db), _pihole(fake), apply=True)
    assert diff is not None and len(diff.failed) == 1
    assert _count(db, "infra.down") == 0
    assert _count(db, "sync.failed") == 1


def test_reconcile_keeps_partial_log_when_pihole_drops(db):
    _seed(db)
    stale = "00:00:5e:00:53:10,192.168.1.12,laptop-a,24h"
    fake = FakePihole([stale], drop_after_writes=1)
    assert reconcile_once(lambda: nullcontext(db), _pihole(fake), apply=True) is None
    assert _count(db, "infra.down") == 1
    applied = db.scalar(select(Event).where(Event.type == "sync.applied"))
    assert applied.payload["removed"] == [stale]


def test_reconcile_without_dhcp_provider_is_noop(db):
    _seed(db)
    assert reconcile_once(lambda: nullcontext(db), lambda _db: None) is None
    assert _count(db, "infra.down") == 0


def test_reconcile_failure_marks_dhcp_down_with_provider_label(db):
    _seed(db)
    factory_for = lambda _db: ("pihole", SPEC.policies, lambda: PiholeProvider(FakePihole(fail=True), CFG))  # noqa: E731
    reconcile_once(lambda: nullcontext(db), factory_for, apply=True)
    ev = db.scalars(select(Event).where(Event.type == "infra.down")).one()
    assert ev.payload["service"] == "dhcp" and ev.payload["provider"] == "Pi-hole"
    assert db.get(Setting, "dhcp.down_since").value is not None


def test_reconcile_config_error_marks_dhcp_down_without_raising(db):
    _seed(db)

    def broken(_db):
        raise ValueError("saved config is not valid")

    assert reconcile_once(lambda: nullcontext(db), broken, apply=True) is None
    ev = db.scalars(select(Event).where(Event.type == "infra.down")).one()
    assert ev.payload["service"] == "dhcp" and "saved config is not valid" in ev.payload["error"]


def test_reconcile_uses_the_policies_of_the_provider(db):
    _seed(db)
    store = FakeStore()
    reconcile_once(lambda: nullcontext(db), lambda _db: ("demo", frozenset({Policy.LAN_ONLY}), lambda: store),
                   apply=True)
    assert store.writes == []   # the authorized laptop needs FULL, which this provider does not offer


def test_dhcp_for_follows_the_dhcp_role(db, monkeypatch):
    monkeypatch.setattr(settings, "dhcp_provider", "")
    monkeypatch.setattr(settings, "dns_provider", "")
    monkeypatch.setattr(settings, "pihole_url", "http://192.168.1.220:1000")
    monkeypatch.setattr(settings, "pihole_password", "pw")
    kind, policies, factory = dhcp_for(db)
    assert (kind, policies) == ("pihole", SPEC.policies)
    assert factory().config.url == "http://192.168.1.220:1000"
    monkeypatch.setattr(settings, "dhcp_provider", "none")
    assert dhcp_for(db) is None


def test_sentinel_heartbeat_outage_is_reported_once(db):
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    db.add(Setting(key="sentinel.heartbeat", value=(now - timedelta(minutes=10)).isoformat()))
    db.flush()
    presence_once(lambda: nullcontext(db), now=now)
    presence_once(lambda: nullcontext(db), now=now + timedelta(minutes=1))
    assert _count(db, "infra.down") == 1
    down = db.scalar(select(Event).where(Event.type == "infra.down"))
    assert down.payload["service"] == "sentinel"
    db.get(Setting, "sentinel.heartbeat").value = (now + timedelta(minutes=2)).isoformat()
    db.flush()
    presence_once(lambda: nullcontext(db), now=now + timedelta(minutes=2))
    assert _count(db, "infra.up") == 1


def test_presence_once_purges_old_sightings(db):
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    db.add(Sighting(mac="00:00:5E:00:53:20", source="arp", ts=now - timedelta(days=45)))
    db.flush()
    presence_once(lambda: nullcontext(db), now=now)
    assert db.scalar(select(func.count()).select_from(Sighting)) == 0


def test_dispatch_once_delivers(db):
    class Sender:
        def __init__(self):
            self.sent = []

        def ready(self, ns):
            return True

        def send(self, message, ns):
            self.sent.append(message.title)

    db.add_all([NotificationRule(**row) for row in default_rule_rows()])
    db.flush()
    senders = {"email": Sender(), "gotify": Sender()}
    debouncer = MemoryDebouncer()
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    dispatch_once(lambda: nullcontext(db), debouncer, now=now, sender_factory=lambda db: senders)
    record_event(db, "device.new", "00:00:5E:00:53:40", {"ip": "192.168.1.243"}, ts=now - timedelta(minutes=1))
    assert dispatch_once(lambda: nullcontext(db), debouncer, now=now, sender_factory=lambda db: senders) == 1
    assert senders["gotify"].sent == ["New device: 00:00:5E:00:53:40"]


def _watched_device(db, last_seen):
    group = Group(name="Meters", color="#A6D86A", icon="device", range_start="192.168.1.120",
                  range_end="192.168.1.129", default_access=Access.lan_only, offline_alert_hours=1)
    db.add_all([group, Device(mac="00:00:5E:00:53:20", name="PLUG", hostname="plug", group=group,
                              access=Access.lan_only, online=True, last_seen=last_seen)])
    db.flush()


def test_offline_alerts_wait_while_scanner_is_down(db):
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    _watched_device(db, now - timedelta(hours=3))
    db.add(Setting(key="sentinel.heartbeat", value=(now - timedelta(hours=2)).isoformat()))
    db.flush()
    presence_once(lambda: nullcontext(db), now=now)
    assert _count(db, "device.offline") == 0
    db.get(Setting, "sentinel.heartbeat").value = now.isoformat()
    db.flush()
    presence_once(lambda: nullcontext(db), now=now + timedelta(minutes=1))
    assert _count(db, "device.offline") == 1


def test_maintenance_start_and_end_are_logged(db):
    from datetime import time as dtime
    from zoneinfo import ZoneInfo

    from app.models import MaintenanceWindow

    rome = ZoneInfo("Europe/Rome")
    db.add(MaintenanceWindow(name="Reboot", start_time=dtime(5, 0), duration_min=15, days=127))
    db.flush()
    for hour, minute in ((4, 55), (5, 1), (5, 5), (5, 20), (5, 25)):
        presence_once(lambda: nullcontext(db), now=datetime(2026, 10, 1, hour, minute, tzinfo=rome))
    assert (_count(db, "maintenance.start"), _count(db, "maintenance.end")) == (1, 1)
