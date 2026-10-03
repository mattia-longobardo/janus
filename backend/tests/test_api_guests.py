import uuid

from sqlalchemy import select

from app.config import settings
from app.models import Device, Event
from app.providers.base import Policy
from tests.fakes_provider import FakeStore, app_override_dhcp


def test_guest_lifecycle(client, db):
    app_override_dhcp(client, None)
    r = client.post("/api/guests", json={"mac": "00:00:5E:00:53:50", "name": "Anna phone", "expires_in_hours": 48})
    assert r.status_code == 201 and r.json()["expiry_source"] == "device"
    gid = r.json()["id"]
    assert [g["id"] for g in client.get("/api/guests").json()] == [gid]
    assert gid not in [d["id"] for d in client.get("/api/devices").json()]
    assert client.patch(f"/api/guests/{gid}", json={"clear_expiry": True}).json()["effective_expires_at"] is None
    assert client.delete(f"/api/guests/{gid}").status_code == 204
    assert client.get("/api/guests").json() == []


def test_past_expiry_is_422(client):
    app_override_dhcp(client, None)
    r = client.post("/api/guests", json={"mac": "00:00:5E:00:53:51", "name": "X", "expires_on": "2000-01-01"})
    assert r.status_code == 422 and "expiry" in r.json()["detail"]


def test_provider_without_guest_policy_is_409(client, db):
    app_override_dhcp(client, ("demo", frozenset({Policy.FULL}), lambda: FakeStore()))
    r = client.post("/api/guests", json={"mac": "00:00:5E:00:53:52", "name": "X"})
    assert r.status_code == 409 and "guests" in r.json()["detail"]


def test_global_rule_round_trip(client):
    app_override_dhcp(client, None)
    assert client.put("/api/guests/settings", json={"auto_remove_hours": 12}).json()["auto_remove_hours"] == 12
    assert client.put("/api/guests/settings", json={"auto_remove_hours": 0}).status_code == 422
    body = client.put("/api/guests/settings", json={"inactive_remove_hours": 48}).json()
    assert body == {"auto_remove_hours": 12, "inactive_remove_hours": 48}


def test_provider_with_guest_policy_is_allowed_and_delete_revokes_lease(client, db, monkeypatch):
    monkeypatch.setattr(settings, "sync_mode", "apply")
    store = FakeStore()
    app_override_dhcp(client, ("demo", frozenset({Policy.FULL, Policy.GUEST}), lambda: store))
    r = client.post("/api/guests", json={"mac": "00:00:5E:00:53:53", "name": "Bo"})
    assert r.status_code == 201
    db.get(Device, uuid.UUID(r.json()["id"])).last_ip = "192.168.1.200"
    db.commit()
    assert client.delete(f"/api/guests/{r.json()['id']}").status_code == 204
    assert ("renew", "00:00:5E:00:53:53") in store.writes
    assert [e.type for e in db.scalars(select(Event).where(Event.type.like("guest.%")).order_by(Event.ts))] == [
        "guest.added", "guest.removed"]


def test_guest_can_be_removed_even_if_provider_lacks_policy(client):
    app_override_dhcp(client, None)
    gid = client.post("/api/guests", json={"mac": "00:00:5E:00:53:54", "name": "Cy"}).json()["id"]
    app_override_dhcp(client, ("demo", frozenset({Policy.FULL}), lambda: FakeStore()))
    assert client.get("/api/guests").status_code == 200
    assert client.patch(f"/api/guests/{gid}", json={"name": "Z"}).status_code == 409
    assert client.delete(f"/api/guests/{gid}").status_code == 204


def test_devices_endpoint_hides_guests_unless_asked_and_refuses_guest_patch(client, db):
    app_override_dhcp(client, None)
    gid = client.post("/api/guests", json={"mac": "00:00:5E:00:53:55", "name": "Di"}).json()["id"]
    assert gid in [d["id"] for d in client.get("/api/devices?access=guest").json()]
    assert gid not in [d["id"] for d in client.get("/api/devices").json()]
    assert client.patch(f"/api/devices/{gid}", json={"access": "guest"}).status_code == 422


def test_pending_device_becomes_guest_through_devices_endpoint(client, db):
    from app.models import Access
    app_override_dhcp(client, None)
    d = Device(mac="00:00:5E:00:53:56", name="Unknown", hostname="unknown-5356", access=Access.pending)
    db.add(d)
    db.commit()
    r = client.post(f"/api/devices/{d.id}/guest", json={"name": "Eve phone", "expires_in_hours": 3})
    assert r.status_code == 200 and r.json()["access"] == "guest" and r.json()["name"] == "Eve phone"
    assert client.post(f"/api/devices/{d.id}/guest", json={"name": "again"}).status_code == 422


def test_absurd_durations_are_422(client):
    app_override_dhcp(client, None)
    for hours in ("1e300", "1e9"):
        r = client.post("/api/guests", content=f'{{"mac": "00:00:5E:00:53:57", "name": "X", "expires_in_hours": {hours}}}',
                        headers={"content-type": "application/json"})
        assert r.status_code == 422


def test_patch_unknown_guest_is_404_even_without_guest_support(client):
    import uuid as _uuid
    app_override_dhcp(client, ("demo", frozenset({Policy.FULL}), lambda: FakeStore()))
    assert client.patch(f"/api/guests/{_uuid.uuid4()}", json={"name": "Z"}).status_code == 404
