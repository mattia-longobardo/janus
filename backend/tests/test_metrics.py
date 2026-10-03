from contextlib import contextmanager
from datetime import UTC, datetime
from urllib.request import urlopen

from app.metrics import render_metrics, start_metrics_server
from app.models import Access, Device, Event, Service, Setting

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


def _seed(db):
    db.add_all([
        Device(mac="00:00:5E:00:53:70", name="PC", hostname="pc", access=Access.authorized, online=True,
               static_ip="192.168.1.10", last_ip="192.168.1.10", last_scan_at=NOW),
        Device(mac="00:00:5E:00:53:71", name="CAM", hostname="cam", access=Access.authorized, online=True,
               static_ip="192.168.1.101", last_ip="192.168.1.170"),
        Device(mac="00:00:5E:00:53:72", name="NEW", hostname="new", access=Access.pending, online=False),
        Service(mac="00:00:5E:00:53:70", port=1900, proto="udp", state="open", risk="warning",
                first_seen=NOW, last_seen=NOW),
        Setting(key="sentinel.heartbeat", value=NOW.isoformat()),
        Setting(key="dhcp.down_since", value=NOW.isoformat()),
        Event(type="device.new", mac="00:00:5E:00:53:72", payload={}, ts=NOW),
        Event(type="device.new", mac="00:00:5E:00:53:71", payload={}, ts=NOW),
    ])
    db.flush()


def _roles(monkeypatch, dhcp="", dns=""):
    from app.config import settings
    monkeypatch.setattr(settings, "dhcp_provider", dhcp)
    monkeypatch.setattr(settings, "dns_provider", dns)
    monkeypatch.setattr(settings, "pihole_url", "http://192.168.1.220:1000")
    monkeypatch.setattr(settings, "pihole_password", "pw")


def test_metrics_text(db, monkeypatch):
    _roles(monkeypatch)
    _seed(db)
    text = render_metrics(db)
    assert "# TYPE janus_devices gauge" in text
    assert 'janus_devices{access="authorized",online="true"} 2' in text
    assert 'janus_devices{access="pending",online="false"} 1' in text
    assert "janus_devices_pending 1" in text
    assert 'janus_devices_health{health="critical"} 1' in text
    assert 'janus_devices_health{health="warning"} 1' in text
    assert f"janus_last_sweep_timestamp_seconds {NOW.timestamp():g}" in text
    assert f"janus_last_port_scan_timestamp_seconds {NOW.timestamp():g}" in text
    assert 'janus_provider_up{role="dhcp"} 0' in text
    assert 'janus_provider_up{role="dns"} 1' in text
    assert "pihole" not in text
    assert "janus_maintenance_active 0" in text
    assert 'janus_sync_mode_info{mode="dry-run"} 1' in text
    assert 'janus_events_total{type="device.new"} 2' in text
    assert text.endswith("\n")


def test_provider_up_has_no_sample_for_a_role_that_is_off(db, monkeypatch):
    _roles(monkeypatch, dhcp="none")
    db.add(Setting(key="dhcp.down_since", value=NOW.isoformat()))
    db.flush()
    text = render_metrics(db)
    assert 'janus_provider_up{role="dhcp"}' not in text and 'janus_provider_up{role="dns"} 1' in text
    _roles(monkeypatch, dhcp="none", dns="none")
    assert "janus_provider_up{" not in render_metrics(db)


def test_metrics_server_serves_only_metrics(db):
    _seed(db)

    @contextmanager
    def factory():
        yield db

    server = start_metrics_server(factory, port=0)
    assert start_metrics_server(factory, port=0) is server
    port = server.server_address[1]
    body = urlopen(f"http://127.0.0.1:{port}/metrics").read().decode()
    assert "janus_devices_pending 1" in body
    try:
        urlopen(f"http://127.0.0.1:{port}/other")
        raise AssertionError("expected 404")
    except Exception as exc:
        assert "404" in str(exc)
    server.shutdown()
