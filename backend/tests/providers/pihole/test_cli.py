from contextlib import nullcontext

import pytest

from app import cli
from app.config import settings
from app.providers import config as pc
from app.providers import registry
from app.providers.base import Role
from app.providers.pihole import cli as pihole_cli
from tests.providers import fixture_pkg


@pytest.fixture(autouse=True)
def _env(db, monkeypatch):
    monkeypatch.setattr(pihole_cli, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(settings, "dhcp_provider", "")
    monkeypatch.setattr(settings, "dns_provider", "")
    monkeypatch.setattr(settings, "pihole_url", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "pihole_password", "pw")
    monkeypatch.setenv("PIHOLE_ADMIN", "admin-pw")


def test_cutover_refuses_when_pihole_is_not_the_dhcp_provider(db, capsys):
    with registry.override({"demo": registry.discover(fixture_pkg)["demo"]}):
        pc.save_role(db, Role.DHCP, "demo", {})
        assert cli.main(["cutover", "--pihole-password-env", "PIHOLE_ADMIN"]) == 2
    err = capsys.readouterr().err
    assert "DHCP role" in err and "Demo router" in err


def test_cutover_refuses_without_a_dhcp_provider(db, capsys, monkeypatch):
    monkeypatch.setattr(settings, "dhcp_provider", "none")
    assert cli.main(["cutover", "--pihole-password-env", "PIHOLE_ADMIN"]) == 2
    assert "no DHCP provider" in capsys.readouterr().err
