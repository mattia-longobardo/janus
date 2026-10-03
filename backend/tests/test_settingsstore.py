import pytest

from app import secretbox
from app.config import settings
from app.models import Setting
from app.settingsstore import OverlayStore, SettingsError, StoreField


def _store():
    def url(v):
        if not str(v).startswith(("http://", "https://")):
            raise SettingsError("url: must start with http:// or https://")
        return str(v).rstrip("/")
    return OverlayStore("test.channel", [
        StoreField("url", lambda: settings.gotify_url, validate=url),
        StoreField("token", lambda: settings.gotify_token, secret=True),
    ])


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "internal_token", "test-token")
    monkeypatch.setattr(settings, "secret_key", "")
    monkeypatch.setattr(settings, "gotify_url", "https://env.example")
    monkeypatch.setattr(settings, "gotify_token", "env-token")


def test_env_is_default_and_saved_value_wins(db, monkeypatch):
    s = _store()
    assert s.load(db) == {"url": "https://env.example", "token": "env-token"}
    s.update(db, {"url": "https://db.example/"})
    monkeypatch.setattr(settings, "gotify_url", "https://env2.example")
    assert s.load(db)["url"] == "https://db.example"
    assert s.sources(db) == {"url": "custom", "token": "env"}


def test_saving_the_env_value_drops_the_override(db, monkeypatch):
    s = _store()
    s.update(db, {"url": "https://db.example"})
    s.update(db, {"url": "https://env.example"})
    assert s.sources(db)["url"] == "env"
    monkeypatch.setattr(settings, "gotify_url", "https://env2.example")
    assert s.load(db)["url"] == "https://env2.example"


def test_secrets_are_encrypted_at_rest_and_hidden_in_view(db):
    s = _store()
    view = s.update(db, {"token": "db-token"})
    assert view["token"] is True
    raw = db.get(Setting, "test.channel").value["token"]
    assert raw.startswith("fernet:") and "db-token" not in raw
    assert s.load(db)["token"] == "db-token"


def test_empty_secret_override_disables_env_value(db):
    s = _store()
    s.update(db, {"token": ""})
    assert s.load(db)["token"] == ""
    assert s.view(db)["token"] is False


def test_rotated_key_reads_as_unset(db, monkeypatch):
    s = _store()
    s.update(db, {"token": "db-token"})
    monkeypatch.setattr(settings, "internal_token", "rotated")
    assert s.load(db)["token"] == ""
    assert s.view(db)["token"] is False


def test_unknown_and_invalid_fields_are_refused(db):
    s = _store()
    with pytest.raises(SettingsError, match="unknown"):
        s.update(db, {"nope": 1})
    with pytest.raises(SettingsError, match="url:"):
        s.update(db, {"url": "ftp://x"})


def test_seal_requires_some_key(monkeypatch):
    monkeypatch.setattr(settings, "internal_token", "")
    with pytest.raises(secretbox.SecretBoxError):
        secretbox.seal("x")
