from app import features
from app.config import settings
from app.providers import config as pc
from app.providers import registry
from app.providers.base import Role
from tests.providers import fixture_pkg


def test_features_collects_every_registered_provider(client, monkeypatch):
    monkeypatch.setattr(features, "FEATURE_PROVIDERS", {
        "notify": lambda db: {"email": True, "gotify": False},
        "guests": lambda db: {"enabled": False},
    })
    assert client.get("/api/features").json() == {
        "notify": {"email": True, "gotify": False},
        "guests": {"enabled": False},
    }


def test_a_broken_provider_does_not_hide_the_others(client, monkeypatch):
    def boom(db):
        raise RuntimeError("down")
    monkeypatch.setattr(features, "FEATURE_PROVIDERS", {"notify": boom, "guests": lambda db: {"enabled": True}})
    assert client.get("/api/features").json() == {"notify": {}, "guests": {"enabled": True}}


def test_features_require_the_internal_token(client):
    assert client.get("/api/features", headers={"X-Janus-Internal-Token": "wrong"}).status_code == 401


def test_guests_feature_on_with_pihole(client, monkeypatch):
    monkeypatch.setattr(settings, "pihole_password", "pw")
    monkeypatch.setattr(settings, "dhcp_provider", "")
    assert client.get("/api/features").json()["guests"]["enabled"] is True


def test_guests_feature_off_with_provider_without_guest_policy(client, db):
    with registry.override({"demo": registry.discover(fixture_pkg)["demo"]}):   # demo supports only Policy.FULL
        pc.save_role(db, Role.DHCP, "demo", {})
        assert client.get("/api/features").json()["guests"]["enabled"] is False


def test_guests_feature_on_without_any_provider(client, db):
    pc.save_role(db, Role.DHCP, None, None)
    assert client.get("/api/features").json()["guests"] == {"enabled": True, "pool": False}


def test_a_failing_provider_rolls_the_session_back_before_the_next(monkeypatch):
    calls = []

    class Session:
        def rollback(self):
            calls.append("rollback")

    def boom(db):
        calls.append("boom")
        raise RuntimeError("query failed: transaction aborted")

    def next_one(db):
        calls.append("next")
        return {"ok": True}

    monkeypatch.setattr(features, "FEATURE_PROVIDERS", {"notify": boom, "guests": next_one})
    assert features.collect(Session()) == {"notify": {}, "guests": {"ok": True}}
    assert calls == ["boom", "rollback", "next"]
