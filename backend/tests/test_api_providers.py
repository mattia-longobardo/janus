import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "dhcp_provider", "")
    monkeypatch.setattr(settings, "dns_provider", "")
    monkeypatch.setattr(settings, "pihole_url", "http://127.0.0.1:9")   # nothing listens: fails fast
    monkeypatch.setattr(settings, "pihole_password", "pw")


def test_list_shows_pihole_and_current_roles(client):
    body = client.get("/api/providers").json()
    assert "pihole" in [p["kind"] for p in body["available"]]
    assert body["roles"]["dhcp"]["kind"] in ("pihole", None) or body["roles"]["dhcp"] is None
    assert "password" not in str([p["schema"].get("default") for p in body["available"]])
    pihole = next(p for p in body["available"] if p["kind"] == "pihole")
    assert pihole["roles"] == ["dhcp", "dns"] and pihole["secret_fields"] == ["password"]
    assert "default" not in pihole["schema"]["properties"]["password"]
    assert body["roles"]["dns"]["shared"] is True


def test_put_invalid_config_is_422(client):
    r = client.put("/api/providers/dhcp", json={"kind": "pihole", "config": {"url": 12}})
    assert r.status_code == 422
    assert r.json()["detail"].startswith("url:")


def test_put_saves_and_returns_the_view(client):
    r = client.put("/api/providers/dhcp", json={"kind": "pihole", "config": {"url": "http://10.0.0.2"}})
    assert r.status_code == 200 and r.json()["config"]["url"] == "http://10.0.0.2" and r.json()["source"] == "custom"
    assert client.get("/api/providers").json()["roles"]["dns"]["config"]["url"] == "http://10.0.0.2"


def test_put_same_as(client):
    client.put("/api/providers/dns", json={"kind": None, "config": None})
    r = client.put("/api/providers/dns", json={"kind": None, "config": None, "same_as": "dhcp"})
    assert r.status_code == 200 and r.json()["shared"] is True


def test_put_unknown_role_is_422(client):
    assert client.put("/api/providers/ntp", json={"kind": None, "config": None}).status_code == 422


def test_features_expose_roles(client):
    client.put("/api/providers/dns", json={"kind": None, "config": None})
    assert client.get("/api/features").json()["providers"]["dns"] is None


def test_test_endpoint_reports_unreachable_provider(client):
    body = client.post("/api/providers/dhcp/test").json()
    assert body["ok"] is False and "unreachable" in body["detail"]


def test_test_endpoint_without_provider(client):
    client.put("/api/providers/dhcp", json={"kind": None, "config": None})
    assert client.post("/api/providers/dhcp/test").json() == {"ok": False, "detail": "no provider configured"}


def test_pihole_router_is_mounted(client):
    assert client.get("/api/providers/pihole/preflight").status_code in (200, 502)


def test_provider_routes_require_the_internal_token(client):
    assert client.get("/api/providers", headers={"X-Janus-Internal-Token": "wrong"}).status_code == 401
    assert client.get("/api/providers/pihole/preflight", headers={"X-Janus-Internal-Token": "wrong"}).status_code == 401
