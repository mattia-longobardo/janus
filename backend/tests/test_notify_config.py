import pytest

from app.config import settings
from app.notify import config as nc
from app.notify.channels import EmailChannel, GotifyChannel
from app.settingsstore import SettingsError


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "internal_token", "test-token")
    for name, value in {"gotify_url": "", "gotify_token": "", "smtp_host": "", "smtp_sender": "",
                        "smtp_user": "", "smtp_password": "", "notify_email": ""}.items():
        monkeypatch.setattr(settings, name, value)


def test_nothing_configured_means_no_channel_ready(db):
    assert nc.channel_ready(db) == {"email": False, "gotify": False}


def test_settings_page_values_take_effect_without_restart(db):
    nc.GOTIFY.update(db, {"url": "https://gotify.example/", "token": "t1"})
    senders = nc.build_senders(db)
    assert isinstance(senders["gotify"], GotifyChannel)
    assert (senders["gotify"].url, senders["gotify"].token) == ("https://gotify.example", "t1")
    nc.GOTIFY.update(db, {"token": "t2"})
    assert nc.build_senders(db)["gotify"].token == "t2"
    assert nc.channel_ready(db)["gotify"] is True


def test_email_needs_host_sender_and_recipient(db, monkeypatch):
    nc.EMAIL.update(db, {"host": "smtp.example", "port": 587, "security": "starttls", "sender": "janus@example.org"})
    assert nc.channel_ready(db)["email"] is False
    monkeypatch.setattr(settings, "notify_email", "me@example.org")
    assert nc.channel_ready(db)["email"] is True
    email = nc.build_senders(db)["email"]
    assert isinstance(email, EmailChannel) and email.security == "starttls"


def test_invalid_values_are_refused(db):
    with pytest.raises(SettingsError, match="url:"):
        nc.GOTIFY.update(db, {"url": "gotify.example"})
    with pytest.raises(SettingsError, match="security:"):
        nc.EMAIL.update(db, {"security": "tls13"})
    with pytest.raises(SettingsError, match="port:"):
        nc.EMAIL.update(db, {"port": 70000})


def test_smtp_host_has_no_hardcoded_default():
    from app.config import Settings

    assert Settings.model_fields["smtp_host"].default == ""
