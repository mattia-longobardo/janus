from contextlib import nullcontext

import pytest

from app.config import settings
from app.models import Access, Device, Event, Group
from app.providers.pihole import SPEC
from app.providers.pihole.provider import PiholeConfig, PiholeProvider
from app.syncmode import load_sync_mode, set_sync_mode
from app.worker import reconcile_once
from tests.fakes import FakePihole


def test_database_mode_overrides_the_environment(db, monkeypatch):
    monkeypatch.setattr(settings, "sync_mode", "dry-run")
    assert load_sync_mode(db) == "dry-run"
    set_sync_mode(db, "apply", "test")
    set_sync_mode(db, "apply", "test")
    assert load_sync_mode(db) == "apply"
    assert [e.payload for e in db.query(Event).filter(Event.type == "sync.mode")] == [
        {"from": "dry-run", "to": "apply", "actor": "test"}]
    with pytest.raises(ValueError):
        set_sync_mode(db, "yolo", "test")


def test_settings_api_and_reconcile_follow_the_stored_mode(client, db, monkeypatch):
    monkeypatch.setattr(settings, "sync_mode", "dry-run")
    group = Group(name="People", color="#6FB7FF", icon="device", range_start="192.168.1.10",
                  range_end="192.168.1.19", default_access=Access.authorized)
    db.add(group)
    db.flush()
    db.add(Device(mac="00:00:5E:00:53:10", name="LAPTOP_A", hostname="laptop-a", group=group,
                  static_ip="192.168.1.10", access=Access.authorized))
    db.flush()
    fake = FakePihole()
    pihole = lambda _db: ("pihole", SPEC.policies, lambda: PiholeProvider(fake, PiholeConfig(url="http://pihole.test")))  # noqa: E731
    reconcile_once(lambda: nullcontext(db), pihole)
    assert fake.writes == []
    set_sync_mode(db, "apply", "test")
    assert client.get("/api/settings").json()["sync_mode"] == "apply"
    reconcile_once(lambda: nullcontext(db), pihole)
    assert fake.hosts == ["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"]
