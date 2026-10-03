import queue
from contextlib import nullcontext
from datetime import UTC, datetime

from scapy.layers.inet import IP, TCP
from scapy.layers.l2 import ARP, Ether
from sqlalchemy import select

from app.config import Settings
from app.models import Device, Setting
from app.net.ipplan import NetworkPlan
from app.sentinel.main import Enqueuer, flush, sniffer_alive, write_heartbeat

PLAN = NetworkPlan.from_settings(Settings())
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def test_flush_records_deduplicated_devices(db):
    packets = [Ether(bytes(Ether() / ARP(op=2, hwsrc="00:00:5e:00:53:40", psrc="192.168.1.243")))] * 3
    assert flush(packets, PLAN, lambda: nullcontext(db), NOW) == 1
    device = db.scalar(select(Device).where(Device.mac == "00:00:5E:00:53:40"))
    assert device.last_ip == "192.168.1.243"


def test_flush_ignores_unparseable_packets(db):
    packets = [Ether(bytes(Ether() / IP() / TCP())), b"garbage", None]
    assert flush(packets, PLAN, lambda: nullcontext(db), NOW) == 0


def test_write_heartbeat(db, tmp_path):
    path = tmp_path / "hb"
    write_heartbeat(lambda: nullcontext(db), path, NOW)
    assert path.exists()
    assert db.get(Setting, "sentinel.heartbeat").value == NOW.isoformat()
    write_heartbeat(lambda: nullcontext(db), path, NOW, dns_probe=lambda: True)
    assert db.get(Setting, "dns.last_ok").value == NOW.isoformat()


def test_enqueuer_drops_when_full():
    q = queue.Queue(maxsize=1)
    enqueue = Enqueuer(q)
    enqueue("a")
    enqueue("b")
    assert q.qsize() == 1 and enqueue.dropped == 1


def test_sniffer_alive():
    class Thread:
        def __init__(self, alive):
            self.alive = alive

        def is_alive(self):
            return self.alive

    class Sniffer:
        def __init__(self, running, thread):
            self.running, self.thread = running, thread

    assert sniffer_alive(Sniffer(True, Thread(True)))
    assert not sniffer_alive(Sniffer(True, Thread(False)))
    assert not sniffer_alive(Sniffer(False, Thread(True)))
    assert not sniffer_alive(Sniffer(True, None))


def test_one_bad_observation_does_not_lose_the_others(db, monkeypatch):
    import app.sentinel.main as sentinel_main

    real = sentinel_main.record_observation

    def flaky(session, obs, plan, now):
        device = real(session, obs, plan, now)
        if obs.mac == "00:00:5E:00:53:41":
            raise RuntimeError("boom after a partial write")
        return device

    monkeypatch.setattr(sentinel_main, "record_observation", flaky)
    packets = [Ether(bytes(Ether() / ARP(op=2, hwsrc=mac, psrc=ip))) for mac, ip in (
        ("00:00:5e:00:53:40", "192.168.1.243"), ("00:00:5e:00:53:41", "192.168.1.244"),
        ("00:00:5e:00:53:42", "192.168.1.245"))]
    assert flush(packets, PLAN, lambda: nullcontext(db), NOW) == 2
    macs = set(db.scalars(select(Device.mac)))
    assert {"00:00:5E:00:53:40", "00:00:5E:00:53:42"} <= macs
    assert "00:00:5E:00:53:41" not in macs


def test_dns_probe_host_comes_from_the_dns_provider(db, monkeypatch):
    from app.config import settings
    from app.sentinel.main import dns_probe_host

    monkeypatch.setattr(settings, "dhcp_provider", "")
    monkeypatch.setattr(settings, "dns_provider", "")
    monkeypatch.setattr(settings, "pihole_url", "http://192.168.1.220:1000")
    monkeypatch.setattr(settings, "pihole_password", "pw")
    assert dns_probe_host(lambda: nullcontext(db)) == "192.168.1.220"
    monkeypatch.setattr(settings, "dns_provider", "none")
    assert dns_probe_host(lambda: nullcontext(db)) is None


def test_heartbeat_without_probe_never_records_a_dns_answer(db, tmp_path):
    write_heartbeat(lambda: nullcontext(db), tmp_path / "hb", NOW, dns_probe=None)
    assert db.get(Setting, "dns.last_ok") is None
