from sqlalchemy import select

from app.models import Event, NotificationRule
from app.notify.store import default_rule_rows


def _seed(db):
    db.add_all([NotificationRule(**row) for row in default_rule_rows()])
    db.flush()


def test_get_returns_settings_and_rules(client, db):
    _seed(db)
    body = client.get("/api/notifications").json()
    assert body["settings"]["quiet_start"] == "23:00" and body["settings"]["enabled"] is True
    new = next(r for r in body["rules"] if r["event_type"] == "device.new")
    assert new == {"event_type": "device.new", "label": "New device waiting for approval", "email": True, "gotify": True,
                   "priority": 8, "default_priority": 8}
    assert all(r["event_type"] != "notify.test" for r in body["rules"])


def test_put_settings_validates(client, db):
    ok = client.put("/api/notifications/settings", json={
        "enabled": True, "quiet_start": "22:30", "quiet_end": "06:45", "email_enabled": True,
        "email_recipient": "owner@example.org", "gotify_enabled": False})
    assert ok.status_code == 200 and client.get("/api/notifications").json()["settings"]["gotify_enabled"] is False
    bad_time = client.put("/api/notifications/settings", json={
        "enabled": True, "quiet_start": "25:00", "quiet_end": None, "email_enabled": True,
        "email_recipient": "", "gotify_enabled": True})
    assert bad_time.status_code == 422
    bad_mail = client.put("/api/notifications/settings", json={
        "enabled": True, "quiet_start": None, "quiet_end": None, "email_enabled": True,
        "email_recipient": "not-an-email", "gotify_enabled": True})
    assert bad_mail.status_code == 422


def test_put_rules(client, db):
    _seed(db)
    response = client.put("/api/notifications/rules", json=[{"event_type": "device.offline", "email": True, "gotify": False}])
    assert response.status_code == 200
    offline = next(r for r in client.get("/api/notifications").json()["rules"] if r["event_type"] == "device.offline")
    assert (offline["email"], offline["gotify"]) == (True, False)
    assert client.put("/api/notifications/rules", json=[{"event_type": "nope", "email": True, "gotify": True}]).status_code == 422


def test_test_notification_is_queued(client, db, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "gotify_url", "https://g.example")
    monkeypatch.setattr(settings, "gotify_token", "tok")
    assert client.post("/api/notifications/test/gotify").status_code == 202
    event = db.scalar(select(Event).where(Event.type == "notify.test"))
    assert event.payload == {"channel": "gotify"}
    assert client.post("/api/notifications/test/sms").status_code == 404


def _rule(client, kind):
    return next(r for r in client.get("/api/notifications").json()["rules"] if r["event_type"] == kind)


def test_put_rules_sets_and_resets_gotify_priority(client, db):
    _seed(db)
    response = client.put("/api/notifications/rules",
                          json=[{"event_type": "device.offline", "email": False, "gotify": True, "priority": 9}])
    assert response.status_code == 200
    offline = _rule(client, "device.offline")
    assert (offline["priority"], offline["default_priority"]) == (9, 5)
    client.put("/api/notifications/rules", json=[{"event_type": "device.offline", "email": False, "gotify": True}])
    assert _rule(client, "device.offline")["priority"] == 9
    client.put("/api/notifications/rules",
               json=[{"event_type": "device.offline", "email": False, "gotify": True, "priority": None}])
    assert _rule(client, "device.offline")["priority"] == 5


def test_put_rules_rejects_out_of_range_priority(client, db):
    _seed(db)
    for bad in (-1, 11, "high"):
        response = client.put("/api/notifications/rules",
                              json=[{"event_type": "device.offline", "email": False, "gotify": True, "priority": bad}])
        assert response.status_code == 422
    assert _rule(client, "device.offline")["priority"] == 5


def test_channels_round_trip_never_returns_secrets(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "gotify_url", "")
    monkeypatch.setattr(settings, "gotify_token", "")
    r = client.put("/api/notifications/channels", json={"gotify": {"url": "https://g.example", "token": "s3cret"}})
    assert r.status_code == 200
    assert r.json()["gotify"]["values"] == {"url": "https://g.example", "token": True}
    assert r.json()["gotify"]["ready"] is True
    assert "s3cret" not in client.get("/api/notifications/channels").text
    assert client.get("/api/features").json()["notify"]["gotify"] is True


def test_channels_change_event_lists_field_names_only(client, db, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "gotify_url", "")
    monkeypatch.setattr(settings, "gotify_token", "")
    client.put("/api/notifications/channels", json={"gotify": {"url": "https://g.example", "token": "s3cret"}})
    event = db.scalar(select(Event).where(Event.type == "settings.channels"))
    assert event.payload == {"changed": {"gotify": ["token", "url"]}}
    assert "s3cret" not in str(event.payload)


def test_invalid_channel_value_is_422(client):
    r = client.put("/api/notifications/channels", json={"email": {"port": "abc"}})
    assert r.status_code == 422 and "port:" in r.json()["detail"]


def test_test_send_on_unconfigured_channel_is_409(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "gotify_url", "")
    assert client.post("/api/notifications/test/gotify").status_code == 409
