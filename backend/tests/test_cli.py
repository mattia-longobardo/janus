import json
from contextlib import nullcontext

import pytest

from app import cli
from app.config import settings
from app.models import Access, Device, Group
from app.providers.base import Policy
from tests.fakes_provider import FakeStore


@pytest.fixture(autouse=True)
def _session(db, monkeypatch):
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(db, "commit", db.flush)


def _seed(db):
    g = Group(name="People", color="#6FB7FF", icon="device", range_start="192.168.1.10",
              range_end="192.168.1.19", default_access=Access.authorized)
    db.add(g)
    db.flush()
    db.add(Device(mac="00:00:5E:00:53:10", name="LAPTOP_A", hostname="laptop-a", group=g,
                  static_ip="192.168.1.10", access=Access.authorized))
    db.flush()


def test_sync_refuses_without_a_dhcp_provider(monkeypatch, capsys):
    monkeypatch.setattr(settings, "dhcp_provider", "none")
    assert cli.main(["sync"]) == 2
    assert "no DHCP provider" in capsys.readouterr().err


def test_sync_talks_to_the_dhcp_role(db, monkeypatch, capsys):
    _seed(db)
    store = FakeStore()
    monkeypatch.setattr(cli, "reservation_provider", lambda _db: ("demo", frozenset({Policy.FULL}), lambda: store))
    assert cli.main(["sync"]) == 0
    assert json.loads(capsys.readouterr().out)["to_add"] == ["00:00:5E:00:53:10,192.168.1.10,laptop-a,full"]
    assert store.writes == []
    assert cli.main(["sync", "--apply"]) == 0
    assert store.writes == [("add", "00:00:5E:00:53:10,192.168.1.10,laptop-a,full")]


def test_provider_commands_are_registered(capsys):
    with pytest.raises(SystemExit):
        cli.main(["cutover"])
    assert "--pihole-password-env" in capsys.readouterr().err   # the cutover parser itself complained
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    usage = capsys.readouterr().out
    assert all(name in usage for name in ("preflight", "backup", "cutover", "rollback"))


def test_sync_mode_switches_enforcement(db, monkeypatch, capsys):
    from app.syncmode import load_sync_mode, set_sync_mode

    set_sync_mode(db, "dry-run", actor="test")
    monkeypatch.setattr(cli, "reservation_provider", lambda _db: ("demo", frozenset({Policy.FULL}), FakeStore))
    assert cli.main(["sync-mode", "apply"]) == 0
    assert load_sync_mode(db) == "apply"
    assert cli.main(["sync-mode", "dry-run"]) == 0
    assert load_sync_mode(db) == "dry-run"
    assert "dry-run" in capsys.readouterr().out


def test_sync_mode_apply_refuses_without_a_dhcp_provider(db, monkeypatch, capsys):
    from app.syncmode import load_sync_mode, set_sync_mode

    set_sync_mode(db, "dry-run", actor="test")
    monkeypatch.setattr(settings, "dhcp_provider", "none")
    assert cli.main(["sync-mode", "apply"]) == 2
    assert "no DHCP provider" in capsys.readouterr().err
    assert load_sync_mode(db) == "dry-run"


def test_sync_mode_refuses_an_unknown_mode():
    with pytest.raises(SystemExit):
        cli.main(["sync-mode", "yolo"])
