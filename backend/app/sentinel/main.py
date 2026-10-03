import logging
import queue
import time
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.dnscheck import dns_answers
from app.models import Setting
from app.net.ipplan import NetworkPlan
from app.netconfig import load_with, restart_needed
from app.providers import runtime
from app.sentinel.observe import observe
from app.sentinel.record import record_observation

log = logging.getLogger("janus.sentinel")
FILTER = "arp or (udp and (port 67 or port 68 or port 137 or port 1900)) or (udp port 5353 and udp[10] & 0x80 != 0)"
HEARTBEAT_KEY = "sentinel.heartbeat"
MAX_QUEUE = 5000
SessionFactory = Callable[[], AbstractContextManager[Session]]


def _safe_observe(packet: Any):
    try:
        return observe(packet)
    except Exception:
        return None


class Enqueuer:
    def __init__(self, target: "queue.Queue[Any]") -> None:
        self.target = target
        self.dropped = 0

    def __call__(self, packet: Any) -> None:
        try:
            self.target.put_nowait(packet)
        except queue.Full:
            self.dropped += 1


def sniffer_alive(sniffer: Any) -> bool:
    thread = getattr(sniffer, "thread", None)
    return bool(getattr(sniffer, "running", False) and thread is not None and thread.is_alive())


def flush(packets: Iterable[Any], plan: NetworkPlan, session_factory: SessionFactory, now: datetime) -> int:
    observations = list(dict.fromkeys(obs for obs in (_safe_observe(p) for p in packets) if obs is not None))
    if not observations:
        return 0
    recorded = 0
    with session_factory() as db:
        for obs in observations:
            try:
                with db.begin_nested():
                    record_observation(db, obs, plan, now)
                recorded += 1
            except Exception:
                log.exception("could not record %s (%s); skipping it", obs.mac, obs.source)
        db.commit()
    return recorded


DNS_OK_KEY = "dns.last_ok"


def dns_probe_host(session_factory: SessionFactory) -> str | None:
    with session_factory() as db:
        return runtime.dns_probe_host(db)


def write_heartbeat(session_factory: SessionFactory, path: Path, now: datetime,
                    dns_probe: Callable[[], bool] | None = None) -> None:
    """Record the sweep, and when the DNS provider last answered (probed from the host network, like the LAN)."""
    with session_factory() as db:
        db.merge(Setting(key=HEARTBEAT_KEY, value=now.isoformat()))
        if dns_probe is not None and dns_probe():
            db.merge(Setting(key=DNS_OK_KEY, value=now.isoformat()))
        db.commit()
    path.touch()


def sweep(iface: str, subnet: str) -> list[Any]:
    from scapy.layers.l2 import ARP, Ether
    from scapy.sendrecv import srp

    answered, _ = srp(Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=subnet), iface=iface, timeout=3, verbose=False)
    return [reply for _, reply in answered]


def main() -> None:
    from scapy.sendrecv import AsyncSniffer

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = load_with(SessionLocal)
    plan = cfg.plan()
    heartbeat = Path(settings.sentinel_heartbeat_path)
    dns_host = dns_probe_host(SessionLocal)   # read at start-up: a new DNS provider is probed after a restart
    dns_probe = (lambda: dns_answers(dns_host)) if dns_host else None
    packets: queue.Queue[Any] = queue.Queue(maxsize=MAX_QUEUE)
    enqueue = Enqueuer(packets)
    sniffer = AsyncSniffer(iface=cfg.sentinel_interface, filter=FILTER, prn=enqueue, store=False)
    sniffer.start()
    log.info("sentinel started on %s (%s), DNS probe: %s", cfg.sentinel_interface, cfg.subnet, dns_host or "off")
    next_sweep = 0.0
    reported_drops = 0
    while True:
        if not sniffer_alive(sniffer):
            log.error("packet sniffer stopped; exiting so the container restarts")
            raise SystemExit(1)
        if enqueue.dropped != reported_drops:
            log.warning("dropped %d packets because the queue was full", enqueue.dropped - reported_drops)
            reported_drops = enqueue.dropped
        batch: list[Any] = []
        if time.monotonic() >= next_sweep:
            try:
                batch.extend(sweep(cfg.sentinel_interface, cfg.subnet))
                write_heartbeat(SessionLocal, heartbeat, datetime.now(UTC), dns_probe=dns_probe)
            except Exception:
                log.exception("ARP sweep failed")
            next_sweep = time.monotonic() + cfg.sweep_interval_s
            try:
                changed = restart_needed(cfg, load_with(SessionLocal))
            except Exception:
                log.exception("reading the network settings failed")
                changed = []
            if changed:
                log.info("network settings changed (%s); exiting so the container restarts", ", ".join(changed))
                sniffer.stop()
                raise SystemExit(0)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                batch.append(packets.get(timeout=0.5))
            except queue.Empty:
                pass
        try:
            flush(batch, plan, SessionLocal, datetime.now(UTC))
        except Exception:
            log.exception("recording observations failed")


if __name__ == "__main__":
    main()
