import pytest

from app import authconfig
from app.config import settings


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "internal_token", "test-token")
    monkeypatch.setattr(settings, "allowed_emails", "a@example.org, B@example.org")
    monkeypatch.setattr(settings, "oidc_id", "cid")
    monkeypatch.setattr(settings, "oidc_secret", "csecret")
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.example/application/o/janus/")


def test_authentik_env_preconfigures_an_oidc_provider(db):
    cfg = authconfig.load(db)
    assert cfg.allowed_emails == ["a@example.org", "b@example.org"]
    [p] = cfg.providers
    assert (p.id, p.source, p.client_secret) == ("authentik", "env", "csecret")
    assert p.discovery_url == "https://auth.example/application/o/janus/.well-known/openid-configuration"


def test_no_env_means_password_only(db, monkeypatch):
    monkeypatch.setattr(settings, "oidc_id", "")
    assert authconfig.load(db).providers == []


def test_public_view_hides_secrets_internal_view_has_them(client):
    r = client.put("/api/settings/auth", json={"allowed_emails": ["c@example.org"], "providers": [
        {"id": "keycloak", "name": "Keycloak", "discovery_url": "https://kc.example/realms/home/.well-known/openid-configuration",
         "client_id": "janus", "client_secret": "kc-secret", "scopes": ["openid", "email", "profile"], "enabled": True}]})
    assert r.status_code == 200
    assert "kc-secret" not in r.text and "csecret" not in r.text
    assert "kc-secret" not in client.get("/api/settings/auth").text
    internal = client.get("/api/internal/auth-config").json()
    assert {p["id"]: p["client_secret"] for p in internal["providers"]} == {"authentik": "csecret", "keycloak": "kc-secret"}
    assert internal["allowed_emails"] == ["c@example.org"]


def test_saving_without_secret_keeps_the_stored_one(client):
    body = {"providers": [{"id": "kc", "name": "KC", "discovery_url": "https://kc.example/.well-known/openid-configuration",
                           "client_id": "j", "client_secret": "one", "scopes": ["openid"], "enabled": True}]}
    client.put("/api/settings/auth", json=body)
    body["providers"][0].pop("client_secret")
    client.put("/api/settings/auth", json=body)
    secrets = {p["id"]: p["client_secret"] for p in client.get("/api/internal/auth-config").json()["providers"]}
    assert secrets["kc"] == "one"


def test_bad_provider_id_or_url_is_422(client):
    r = client.put("/api/settings/auth", json={"providers": [{"id": "Bad Id", "name": "x", "discovery_url": "nope",
                                                              "client_id": "j", "scopes": ["openid"], "enabled": True}]})
    assert r.status_code == 422


def test_custom_provider_with_env_id_wins_and_can_disable_it(client):
    client.put("/api/settings/auth", json={"providers": [
        {"id": "authentik", "name": "SSO", "discovery_url": "https://sso.example/.well-known/openid-configuration",
         "client_id": "x", "scopes": ["openid"], "enabled": False}]})
    pub = client.get("/api/settings/auth").json()
    assert [(p["id"], p["source"], p["enabled"], p["client_secret"]) for p in pub["providers"]] == [("authentik", "custom", False, False)]
    assert client.get("/api/internal/auth-config").json()["providers"] == []


def test_allowed_emails_source_and_version_changes(client):
    assert client.get("/api/settings/auth").json()["allowed_emails_source"] == "env"
    v1 = client.get("/api/internal/auth-config").json()["version"]
    client.put("/api/settings/auth", json={"allowed_emails": ["z@example.org"]})
    pub = client.get("/api/settings/auth").json()
    assert (pub["allowed_emails"], pub["allowed_emails_source"]) == (["z@example.org"], "custom")
    assert client.get("/api/internal/auth-config").json()["version"] != v1


def test_private_http_discovery_allowed_public_http_rejected(client):
    def put(url):
        return client.put("/api/settings/auth", json={"providers": [
            {"id": "lan", "name": "L", "discovery_url": url, "client_id": "j", "scopes": ["openid"], "enabled": True}]})
    assert put("http://192.168.1.5:9000/.well-known/openid-configuration").status_code == 200
    assert put("http://8.8.8.8/.well-known/openid-configuration").status_code == 422
    assert put("https://kc.example/x").status_code == 200


def test_saving_env_equal_emails_drops_the_override(client, monkeypatch):
    client.put("/api/settings/auth", json={"allowed_emails": ["z@example.org"]})
    client.put("/api/settings/auth", json={"allowed_emails": ["B@example.org", "a@example.org"]})
    assert client.get("/api/settings/auth").json()["allowed_emails_source"] == "env"
    monkeypatch.setattr(settings, "allowed_emails", "new@example.org")
    assert client.get("/api/settings/auth").json()["allowed_emails"] == ["new@example.org"]


def test_round_tripping_the_env_provider_keeps_it_env(client, monkeypatch):
    pub = client.get("/api/settings/auth").json()
    pub["providers"][0].pop("client_secret")
    pub["providers"][0].pop("source")
    assert client.put("/api/settings/auth", json={"providers": pub["providers"]}).status_code == 200
    assert client.get("/api/settings/auth").json()["providers"][0]["source"] == "env"
    monkeypatch.setattr(settings, "oidc_issuer", "https://other.example/o/janus/")
    [p] = client.get("/api/internal/auth-config").json()["providers"]
    assert p["discovery_url"] == "https://other.example/o/janus/.well-known/openid-configuration"


def test_env_secret_is_inherited_only_for_the_same_client_id(client):
    base = {"id": "authentik", "name": "A", "discovery_url": "https://x.example/.well-known/openid-configuration",
            "scopes": ["openid"], "enabled": True}
    client.put("/api/settings/auth", json={"providers": [{**base, "client_id": "cid"}]})
    assert [p["client_secret"] for p in client.get("/api/internal/auth-config").json()["providers"]] == ["csecret"]
    client.put("/api/settings/auth", json={"providers": [{**base, "client_id": "other"}]})
    assert client.get("/api/internal/auth-config").json()["providers"] == []


def test_oidc_id_without_issuer_is_no_provider(db, monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "")
    assert authconfig.load(db).providers == []


def test_bad_discovery_url_with_valid_id_is_422(client):
    r = client.put("/api/settings/auth", json={"providers": [{"id": "good-id", "name": "x", "discovery_url": "nope",
                                                              "client_id": "j", "scopes": ["openid"], "enabled": True}]})
    assert r.status_code == 422
