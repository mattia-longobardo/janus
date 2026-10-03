import uuid

import pytest

from app.config import settings
from app.models import Access, Device, Group
from app.providers.base import Policy
from app.providers.pihole import SPEC
from app.providers.pihole.provider import PiholeConfig, PiholeProvider
from tests.fakes import FakePihole
from tests.fakes_provider import FakeStore, app_override_dhcp

CFG = PiholeConfig(url="http://192.168.1.220:1000", password="pw", lease="24h")


@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    monkeypatch.setattr(settings, "sync_mode", "dry-run")


@pytest.fixture
def people(db):
    group = Group(name="People", color="#6FB7FF", icon="device", range_start="192.168.1.10",
                  range_end="192.168.1.19", default_access=Access.authorized)
    db.add(group)
    db.flush()
    return group


@pytest.fixture
def pending(db):
    device = Device(mac="00:00:5E:00:53:40", name="pixel-7", hostname="pixel-7", access=Access.pending,
                    last_ip="192.168.1.243")
    db.add(device)
    db.flush()
    return device


def _use(client, fake):
    app_override_dhcp(client, ("pihole", SPEC.policies, lambda: PiholeProvider(fake, CFG)))


def seed_pending(db):
    group = Group(name="Meters", color="#A6D86A", icon="device", range_start="192.168.1.120",
                  range_end="192.168.1.129", default_access=Access.authorized)
    device = Device(mac="00:00:5E:00:53:41", name="plug", hostname="plug", access=Access.pending,
                    last_ip="192.168.1.244")
    db.add_all([group, device])
    db.flush()
    return device, group


def test_approve_endpoint_dry_run(client, people, pending):
    fake = FakePihole()
    _use(client, fake)
    response = client.post(f"/api/devices/{pending.id}/approve", json={"name": "Phone B", "group_id": people.id})
    assert response.status_code == 200
    body = response.json()
    assert (body["device"]["access"], body["device"]["static_ip"], body["enforcement"]) == (
        "authorized", "192.168.1.10", "dry-run")
    assert fake.writes == []


def test_approve_endpoint_apply_mode_syncs_and_revokes_quarantine_lease(client, people, pending, monkeypatch):
    monkeypatch.setattr(settings, "sync_mode", "apply")
    fake = FakePihole()
    _use(client, fake)
    body = client.post(f"/api/devices/{pending.id}/approve", json={"name": "Phone B", "group_id": people.id}).json()
    assert body["enforcement"] == "applied"
    assert fake.hosts == ["00:00:5e:00:53:40,192.168.1.10,phone-b,24h"]
    assert ("revoke", "192.168.1.243") in fake.writes


def test_block_endpoint_apply_revokes_current_lease(client, pending, monkeypatch):
    monkeypatch.setattr(settings, "sync_mode", "apply")
    fake = FakePihole()
    _use(client, fake)
    body = client.post(f"/api/devices/{pending.id}/block").json()
    assert body["device"]["access"] == "blocked" and body["enforcement"] == "applied"
    assert fake.writes == [("revoke", "192.168.1.243")]


def test_enforcement_failure_is_reported(client, people, pending, monkeypatch):
    monkeypatch.setattr(settings, "sync_mode", "apply")
    _use(client, FakePihole(fail=True))
    response = client.post(f"/api/devices/{pending.id}/approve", json={"name": "Phone B", "group_id": people.id})
    assert response.status_code == 200
    assert response.json()["enforcement"].startswith("failed: ")
    assert response.json()["device"]["access"] == "authorized"


def test_approve_validation_errors(client, people, pending):
    _use(client, FakePihole())
    unknown_group = client.post(f"/api/devices/{pending.id}/approve", json={"name": "X", "group_id": 9999})
    assert unknown_group.status_code == 422
    bad_ip = client.post(f"/api/devices/{pending.id}/approve",
                         json={"name": "X", "group_id": people.id, "static_ip": "192.168.1.50"})
    assert bad_ip.status_code == 422 and "outside the group range" in bad_ip.json()["detail"]
    missing = client.post(f"/api/devices/{uuid.uuid4()}/approve", json={"name": "X", "group_id": people.id})
    assert missing.status_code == 404


def test_approve_with_unsupported_policy_is_409(client, db, monkeypatch):
    # fake DHCP provider that only supports FULL
    app_override_dhcp(client, ("demo", frozenset({Policy.FULL}), lambda: FakeStore()))
    device, group = seed_pending(db)
    r = client.post(f"/api/devices/{device.id}/approve", json={"name": "Plug", "group_id": group.id, "access": "lan_only"})
    assert r.status_code == 409 and "lan_only" in r.json()["detail"]
    db.refresh(device)
    assert device.access is Access.pending


def test_approve_without_provider_reports_no_provider(client, db):
    app_override_dhcp(client, None)
    device, group = seed_pending(db)
    r = client.post(f"/api/devices/{device.id}/approve", json={"name": "Laptop", "group_id": group.id})
    assert r.status_code == 200 and r.json()["enforcement"] == "no provider"


def test_block_without_provider_reports_no_provider(client, db, monkeypatch):
    monkeypatch.setattr(settings, "sync_mode", "apply")
    app_override_dhcp(client, None)
    device, _ = seed_pending(db)
    r = client.post(f"/api/devices/{device.id}/block")
    assert r.status_code == 200 and r.json()["enforcement"] == "no provider"


def test_block_apply_asks_the_provider_to_renew_and_leaves_no_reservation(client, db, monkeypatch):
    monkeypatch.setattr(settings, "sync_mode", "apply")
    store = FakeStore()
    app_override_dhcp(client, ("demo", frozenset({Policy.FULL, Policy.LAN_ONLY}), lambda: store))
    device, _ = seed_pending(db)
    assert client.post(f"/api/devices/{device.id}/block").json()["enforcement"] == "applied"
    assert store.writes == [("renew", "00:00:5E:00:53:41")]


def test_block_apply_revokes_the_lease_of_a_device_without_mac(client, db, monkeypatch):
    monkeypatch.setattr(settings, "sync_mode", "apply")
    device = Device(mac=None, name="ghost", hostname="ghost", access=Access.pending, last_ip="192.168.1.245")
    db.add(device)
    db.flush()
    fake = FakePihole()
    _use(client, fake)
    assert client.post(f"/api/devices/{device.id}/block").json()["enforcement"] == "applied"
    assert fake.writes == [("revoke", "192.168.1.245")]
