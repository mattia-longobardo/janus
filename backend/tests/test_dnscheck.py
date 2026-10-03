import socket
import threading

import pytest
from sqlalchemy import select

from app.config import settings
from app.dnscheck import dns_answers
from app.models import Event, Setting
from app.worker import dns_check_once


@pytest.fixture(autouse=True)
def _pihole_dns(monkeypatch):
    monkeypatch.setattr(settings, "dhcp_provider", "")
    monkeypatch.setattr(settings, "dns_provider", "")
    monkeypatch.setattr(settings, "pihole_url", "http://192.168.1.220:1000")
    monkeypatch.setattr(settings, "pihole_password", "pw")


def _server(reply: bool) -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))

    def serve() -> None:
        try:
            data, addr = sock.recvfrom(512)
        except OSError:
            return
        if reply:
            sock.sendto(data[:2] + b"\x81\x83" + data[4:], addr)

    threading.Thread(target=serve, daemon=True).start()
    return sock, sock.getsockname()[1]


def test_probe_sees_any_reply_and_times_out_on_silence():
    alive, port = _server(reply=True)
    assert dns_answers("127.0.0.1", port=port, timeout=1, attempts=1) is True
    alive.close()
    silent, port = _server(reply=False)
    assert dns_answers("127.0.0.1", port=port, timeout=0.2, attempts=2) is False
    silent.close()


class _Session:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        return False


def test_dns_outage_is_judged_from_the_sentinel_answers(db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from app.sentinel.main import write_heartbeat

    monkeypatch.setattr(db, "commit", db.flush)
    factory = lambda: _Session(db)  # noqa: E731
    now = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
    assert dns_check_once(factory, now) is None
    write_heartbeat(factory, _heartbeat_path(), now, dns_probe=lambda: True)
    assert dns_check_once(factory, now + timedelta(minutes=2)) is True
    write_heartbeat(factory, _heartbeat_path(), now + timedelta(minutes=2), dns_probe=lambda: False)
    assert dns_check_once(factory, now + timedelta(minutes=4)) is False
    assert dns_check_once(factory, now + timedelta(minutes=5)) is False
    write_heartbeat(factory, _heartbeat_path(), now + timedelta(minutes=6), dns_probe=lambda: True)
    assert dns_check_once(factory, now + timedelta(minutes=6)) is True
    events = list(db.scalars(select(Event).where(Event.type.like("infra.%")).order_by(Event.id)))
    assert [e.type for e in events] == ["infra.down", "infra.up"]
    assert {(e.payload["service"], e.payload["provider"]) for e in events} == {("dns", "Pi-hole")}
    assert "Pi-hole" in events[0].payload["error"]
    assert db.get(Setting, "dns.down_since").value is None
    assert db.get(Setting, "dns.last_ok").value == (now + timedelta(minutes=6)).isoformat()


def test_dns_check_is_off_without_a_dns_probe_and_drops_an_open_outage_silently(db, monkeypatch):
    from datetime import UTC, datetime

    monkeypatch.setattr(db, "commit", db.flush)
    monkeypatch.setattr(settings, "dns_provider", "none")
    now = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
    db.add_all([Setting(key="dns.last_ok", value="2026-10-01T20:00:00+00:00"),
                Setting(key="dns.down_since", value="2026-10-01T20:03:00+00:00")])
    db.flush()
    assert dns_check_once(lambda: _Session(db), now) is None
    assert db.get(Setting, "dns.down_since").value is None
    assert dns_check_once(lambda: _Session(db), now) is None
    assert list(db.scalars(select(Event).where(Event.type.like("infra.%")))) == []


def _heartbeat_path():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp()) / "heartbeat"
