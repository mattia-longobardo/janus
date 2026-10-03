def test_get_settings_defaults(client):
    body = client.get("/api/settings").json()
    assert (body["timezone"], body["time_format"], body["sync_mode"]) == ("Europe/Rome", "24h", "dry-run")
    assert body["network"]["subnet"] == "192.168.1.0/24"
    assert body["network"]["quarantine_start"] == "192.168.1.240"
    assert body["network"]["guest_start"] == "" and body["network"]["guest_end"] == ""
    assert body["scan_window"] == {"start": "08:00", "end": "22:00"}


def test_put_settings(client):
    body = client.put("/api/settings", json={"timezone": "Europe/London", "time_format": "12h"}).json()
    assert (body["timezone"], body["time_format"]) == ("Europe/London", "12h")
    assert client.get("/api/settings").json()["timezone"] == "Europe/London"


def test_put_settings_rejects_unknown_zone_and_format(client):
    assert client.put("/api/settings", json={"timezone": "Mars/Olympus"}).status_code == 422
    assert client.put("/api/settings", json={"time_format": "36h"}).status_code == 422


def test_settings_report_infrastructure_status(client, db):
    from app.models import Setting

    db.add_all([Setting(key="dhcp.down_since", value="2026-10-01T05:00:00+00:00"),
                Setting(key="dns.down_since", value="2026-10-01T06:00:00+00:00"),
                Setting(key="sentinel.heartbeat", value="2026-10-01T10:00:00+00:00")])
    db.flush()
    status = client.get("/api/settings").json()["status"]
    assert status == {"dhcp_down_since": "2026-10-01T05:00:00+00:00", "dns_down_since": "2026-10-01T06:00:00+00:00", "sentinel_down_since": None,
                      "last_sweep_at": "2026-10-01T10:00:00+00:00", "maintenance_active": False}
