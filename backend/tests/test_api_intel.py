import time
from datetime import UTC, datetime

import pytest

from app.models import Access, Device, DeviceFact, Service
from app.providers.pihole.provider import PiholeConfig, PiholeProvider
from tests.fakes import FakePihole
from tests.fakes_provider import app_override_dns

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
CFG = PiholeConfig(url="http://192.168.1.220:1000", password="pw")


def _use(client, fake):
    app_override_dns(client, ("pihole", lambda: PiholeProvider(fake, CFG)))


def seed_device(db):
    d = Device(mac="00:00:5E:00:53:42", name="Plug", hostname="plug", access=Access.authorized, online=True,
               last_ip="192.168.1.42")
    db.add(d)
    db.flush()
    return d


@pytest.fixture
def device(db):
    d = Device(mac="00:00:5E:00:53:40", name="TV", hostname="tv", access=Access.authorized, online=True,
               last_ip="192.168.1.40")
    db.add(d)
    db.flush()
    return d


def test_facts_summary(client, db, device):
    db.add_all([
        DeviceFact(mac=device.mac, field="type", value="Embedded device", source="dhcp", confidence=60, observed_at=NOW),
        DeviceFact(mac=device.mac, field="type", value="Chromecast / Google TV", source="mdns", confidence=80,
                   observed_at=NOW),
    ])
    db.flush()
    body = client.get(f"/api/devices/{device.id}/facts").json()
    assert body["summary"]["type"]["value"] == "Chromecast / Google TV"
    assert {(f["value"], f["source"]) for f in body["facts"]} == {("Embedded device", "dhcp"),
                                                                   ("Chromecast / Google TV", "mdns")}


def test_services_open_by_default(client, db, device):
    db.add_all([
        Service(mac=device.mac, port=22, proto="tcp", state="open", service="ssh", risk="none", first_seen=NOW,
                last_seen=NOW),
        Service(mac=device.mac, port=23, proto="tcp", state="closed", service="telnet", risk="high",
                risk_reason="Telnet sends passwords in clear text", first_seen=NOW, last_seen=NOW),
    ])
    db.flush()
    assert [s["port"] for s in client.get(f"/api/devices/{device.id}/services").json()] == [22]
    assert [s["port"] for s in client.get(f"/api/devices/{device.id}/services", params={"all": True}).json()] == [22, 23]


def test_scan_request(client, db, device):
    assert client.post(f"/api/devices/{device.id}/scan").status_code == 202
    db.refresh(device)
    assert device.scan_requested_at is not None
    device.last_ip = None
    db.flush()
    assert client.post(f"/api/devices/{device.id}/scan").status_code == 422
    device.last_ip = "203.0.113.5"
    db.flush()
    assert client.post(f"/api/devices/{device.id}/scan").status_code == 422


def test_dns_activity(client, device):
    now = time.time()
    fake = FakePihole()
    fake.queries = [
        {"time": now - 60, "domain": "api.example.org", "status": "FORWARDED", "client": {"ip": "192.168.1.40"}},
        {"time": now - 50, "domain": "api.example.org", "status": "CACHE", "client": {"ip": "192.168.1.40"}},
        {"time": now - 40, "domain": "ads.example.net", "status": "GRAVITY", "client": {"ip": "192.168.1.40"}},
        {"time": now - 30, "domain": "other.example", "status": "FORWARDED", "client": {"ip": "192.168.1.41"}},
        {"time": now - 90000, "domain": "old.example", "status": "FORWARDED", "client": {"ip": "192.168.1.40"}},
    ]
    _use(client, fake)
    body = client.get(f"/api/devices/{device.id}/dns").json()
    assert body == {"total": 3, "sampled": 3, "truncated": False, "blocked": 1, "domains": [
        {"domain": "api.example.org", "count": 2, "blocked": False},
        {"domain": "ads.example.net", "count": 1, "blocked": True},
    ]}
    _use(client, FakePihole(fail=True))
    assert client.get(f"/api/devices/{device.id}/dns").status_code == 502


def test_dns_reports_truncation_and_uses_disk_for_long_windows(client, device):
    fake = FakePihole()
    fake.queries = [{"time": time.time() - 10, "domain": "a.example", "status": "FORWARDED",
                     "client": {"ip": "192.168.1.40"}}] * 3
    fake.reported_total = 12000
    _use(client, fake)
    body = client.get(f"/api/devices/{device.id}/dns", params={"hours": 72}).json()
    assert (body["total"], body["sampled"], body["truncated"]) == (12000, 3, True)
    assert fake.last_query["disk"] is True
    client.get(f"/api/devices/{device.id}/dns", params={"hours": 12})
    assert fake.last_query["disk"] is False


def test_dns_routes_are_404_without_dns_provider(client, db):
    app_override_dns(client, None)
    d = seed_device(db)
    assert client.get(f"/api/devices/{d.id}/dns").status_code == 404
    r = client.get(f"/api/devices/{d.id}/dns/analysis")
    assert r.status_code == 404 and r.json()["detail"] == "no DNS provider with a query log"
