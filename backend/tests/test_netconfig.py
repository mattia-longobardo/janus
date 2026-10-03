from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.intel.scanning import on_lan, pick_next
from app.models import Access, Device, Event, Group, Setting
from app.netconfig import NETWORK_KEY, env_defaults, load_netconfig, restart_needed

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def people(db):
    group = Group(name="People", color="#6FB7FF", icon="device", range_start="192.168.1.10",
                  range_end="192.168.1.19", default_access=Access.authorized, scan_enabled=True, scan_interval_hours=24)
    db.add(group)
    db.flush()
    return group


def test_defaults_come_from_env_and_are_marked(client):
    body = client.get("/api/settings").json()
    assert body["network"]["subnet"] == "192.168.1.0/24"
    assert body["source"]["subnet"] == "env"
    assert set(body["source"]) >= {"pihole_url", "sentinel_interface", "sweep_interval_s", "scan_window_start"}


def test_override_is_applied_and_logged(client, db, people):
    response = client.put("/api/settings", json={"network": {
        "pihole_url": "http://192.168.1.221:8080/", "sweep_interval_s": 120, "sentinel_interface": "eth1",
        "scan_window_start": "09:00", "quarantine_start": "192.168.1.230"}})
    assert response.status_code == 200
    body = response.json()
    assert body["network"]["pihole_url"] == "http://192.168.1.221:8080"
    assert body["network"]["sweep_interval_s"] == 120
    assert body["network"]["quarantine_start"] == "192.168.1.230"
    assert body["scan_window"]["start"] == "09:00"
    assert body["source"]["pihole_url"] == "custom"
    assert body["source"]["subnet"] == "env"
    assert load_netconfig(db).sentinel_interface == "eth1"
    event = db.scalars(select(Event).where(Event.type == "settings.network")).one()
    assert event.payload["changes"]["sweep_interval_s"] == [60, 120]


def test_null_resets_a_field_to_its_default(client, db):
    client.put("/api/settings", json={"network": {"sweep_interval_s": 300, "sentinel_interface": "eth1"}})
    body = client.put("/api/settings", json={"network": {"sweep_interval_s": None}}).json()
    assert body["network"]["sweep_interval_s"] == 60
    assert body["source"]["sweep_interval_s"] == "env"
    assert body["source"]["sentinel_interface"] == "custom"
    assert db.get(Setting, NETWORK_KEY).value == {"sentinel_interface": "eth1"}


def test_setting_a_value_equal_to_the_default_is_not_stored_as_custom(client):
    body = client.put("/api/settings", json={"network": {"sweep_interval_s": 60}}).json()
    assert body["source"]["sweep_interval_s"] == "env"


@pytest.mark.parametrize("patch, message", [
    ({"subnet": "not-a-network"}, "subnet"),
    ({"gateway": "10.0.0.1"}, "outside"),
    ({"quarantine_start": "192.168.1.250", "quarantine_end": "192.168.1.240"}, "start is after end"),
    ({"pihole_url": "ftp://pihole"}, "http(s)"),
    ({"sentinel_interface": "eth0; rm -rf /"}, "sentinel_interface"),
    ({"sweep_interval_s": 5}, "between 10 and 3600"),
    ({"scan_window_end": "25:00"}, "HH:MM"),
    ({"subnet": "10.0.0.0/24", "gateway": "10.0.0.1", "quarantine_start": "10.0.0.240",
      "quarantine_end": "10.0.0.254"}, "group People"),
])
def test_invalid_values_are_rejected_without_saving(client, db, people, patch, message):
    response = client.put("/api/settings", json={"network": patch, "time_format": "12h"})
    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert db.get(Setting, NETWORK_KEY) is None
    assert client.get("/api/settings").json()["time_format"] == "24h"


def test_quarantine_pool_cannot_overlap_a_group(client, people):
    response = client.put("/api/settings", json={"network": {"quarantine_start": "192.168.1.15"}})
    assert response.status_code == 422
    assert "overlaps group People" in response.json()["detail"]


def test_unknown_network_fields_are_rejected(client):
    assert client.put("/api/settings", json={"network": {"dns": "1.1.1.1"}}).status_code == 422


def test_scanner_uses_the_overridden_subnet(client, db, people):
    device = Device(mac="00:00:5E:00:53:20", name="NAS", hostname="nas", group=people, access=Access.authorized,
                    online=True, last_ip="192.168.1.12", scan_requested_at=NOW)
    db.add(device)
    db.flush()
    assert pick_next(db, NOW, muted=False, quiet=False) is device
    db.add(Setting(key=NETWORK_KEY, value={"subnet": "192.168.1.0/27", "quarantine_start": "192.168.1.20",
                                           "quarantine_end": "192.168.1.30"}))
    db.flush()
    assert load_netconfig(db).subnet == "192.168.1.0/27"
    assert on_lan("192.168.1.12", load_netconfig(db).subnet) is True
    assert on_lan("192.168.1.40", load_netconfig(db).subnet) is False


def test_scan_request_refuses_hosts_outside_the_overridden_subnet(client, db, people):
    device = Device(mac="00:00:5E:00:53:21", name="FAR", hostname="far", group=people, access=Access.authorized,
                    online=True, last_ip="192.168.1.100")
    db.add(device)
    db.add(Setting(key=NETWORK_KEY, value={"subnet": "192.168.1.0/27", "quarantine_start": "192.168.1.20",
                                           "quarantine_end": "192.168.1.30"}))
    db.flush()
    response = client.post(f"/api/devices/{device.id}/scan")
    assert response.status_code == 422
    assert "not on the home network" in response.json()["detail"]


def test_invalid_stored_overrides_fall_back_to_env(db):
    db.add(Setting(key=NETWORK_KEY, value={"subnet": "garbage"}))
    db.flush()
    assert load_netconfig(db) == env_defaults()


def test_restart_needed_only_for_fields_the_sentinel_binds():
    base = env_defaults()
    assert restart_needed(base, base) == []
    assert restart_needed(base, replace(base, pihole_url="http://x", scan_window_start="09:00")) == []
    assert restart_needed(base, replace(base, sentinel_interface="eth1", sweep_interval_s=30)) == [
        "sentinel_interface", "sweep_interval_s"]
    assert restart_needed(base, replace(base, quarantine_end="192.168.1.250")) == ["quarantine_end"]


def test_saving_the_env_value_drops_the_override(db):
    from app.netconfig import env_defaults, sources, update_netconfig

    update_netconfig(db, {"sweep_interval_s": 120})
    assert sources(db)["sweep_interval_s"] == "custom"
    update_netconfig(db, {"sweep_interval_s": env_defaults().sweep_interval_s})
    assert sources(db)["sweep_interval_s"] == "env"
