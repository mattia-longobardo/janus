from zoneinfo import ZoneInfo

from app.models import Event
from app.notify.render import render

ROME = ZoneInfo("Europe/Rome")
BASE = "https://janus.example"


def _render(kind, payload, mac="00:00:5E:00:53:40", name=None, quarantine=False):
    return render(Event(type=kind, mac=mac, payload=payload), name, base_url=BASE, tz=ROME, quarantine_active=quarantine)


def test_new_device_message_depends_on_quarantine():
    payload = {"device_id": "abc", "ip": "192.168.1.243", "private_mac": True}
    detected = _render("device.new", payload, name="pixel-7")
    assert detected.title == "New device: pixel-7"
    assert detected.body == "MAC 00:00:5E:00:53:40 · IP 192.168.1.243 · private MAC\nDetected on the network; quarantine is not active yet."
    assert (detected.priority, detected.url) == (8, f"{BASE}/devices/abc")
    assert _render("device.new", payload, name="pixel-7", quarantine=True).body.endswith("No internet access until you approve it.")


def test_offline_message_uses_local_time():
    message = _render("device.offline", {"device_id": "abc", "name": "PLUG", "hours": 6,
                                          "last_seen": "2026-10-01T03:00:00+00:00"}, name="PLUG")
    assert (message.title, message.body) == ("Offline: PLUG", "Not seen for more than 6 h (last seen 01/10 05:00)")


def test_infra_messages_name_the_service():
    down = _render("infra.down", {"service": "pihole", "error": "Pi-hole unreachable: refused"}, mac=None)
    assert (down.title, down.body, down.url) == ("Pi-hole unreachable", "Pi-hole unreachable: refused", BASE)
    dhcp = _render("infra.down", {"service": "dhcp", "provider": "Pi-hole", "error": "refused"}, mac=None)
    assert dhcp.title == "Pi-hole DHCP unreachable"
    dns = _render("infra.up", {"service": "dns", "provider": "Pi-hole", "down_since": "2026-10-01T03:00:00+00:00"},
                  mac=None)
    assert dns.title == "Pi-hole DNS reachable again"
    assert _render("infra.down", {"service": "dns", "error": "x"}, mac=None).title == "DNS unreachable"
    assert _render("infra.down", {"service": "pihole_dns", "error": "x"}, mac=None).title == "Pi-hole DNS unreachable"
    up = _render("infra.up", {"service": "sentinel", "down_since": "2026-10-01T03:00:00+00:00"}, mac=None)
    assert (up.title, up.body) == ("Scanner reachable again", "Down since 01/10 05:00")


def test_conflict_mismatch_private_and_test():
    assert _render("ip.conflict", {"ip": "192.168.1.10", "macs": ["A", "B"]}).body == "Claimed by A, B"
    conflict = _render("ip.conflict", {
        "ip": "192.168.1.155", "reserved": True,
        "claimant": {"name": "TV_KITCHEN", "mac": "00:00:5E:00:53:70", "device_id": "k"},
        "owner": {"name": "TV_SALA", "mac": "00:00:5E:00:53:71", "device_id": "s"},
    })
    assert conflict.title == "TV_KITCHEN is trying to take 192.168.1.155"
    assert conflict.body == ("TV_KITCHEN (00:00:5E:00:53:70) is trying to take 192.168.1.155, "
                             "which is assigned to TV_SALA (00:00:5E:00:53:71).")
    assert conflict.url.endswith("/devices/k")
    mismatch = _render("device.ip_mismatch", {"device_id": "d", "ip": "192.168.1.17", "expected": "192.168.1.10"}, name="LAPTOP")
    assert (mismatch.title, mismatch.body) == ("LAPTOP is using 192.168.1.17", "Its reserved address is 192.168.1.10")
    private = _render("device.private_mac", {"device_id": "d", "previous_name": "LAPTOP", "previous_mac": "M"}, name="new")
    assert private.title == "new changed its MAC"
    assert _render("notify.test", {"channel": "email"}, mac=None).title == "Janus test notification"
    assert _render("device.approved", {"device_id": "d", "ip": "192.168.1.10", "access": "lan_only"}, name="P").body == "192.168.1.10 · LAN only"


def test_security_messages():
    new_port = _render("security.new_port", {"device_id": "d", "port": 8080, "proto": "tcp", "service": "http",
                                               "version": "nginx 1.24"}, name="PI")
    assert (new_port.title, new_port.body, new_port.priority) == ("New open port on PI", "8080/tcp http nginx 1.24", 6)
    risky = _render("security.risky_service", {"device_id": "d", "port": 23, "proto": "tcp", "service": "telnet",
                                                 "reason": "Telnet sends passwords in clear text"}, name="CAM")
    assert (risky.title, risky.body, risky.priority) == (
        "Risky service on CAM", "23/tcp telnet: Telnet sends passwords in clear text", 8)


def test_combined_risky_message():
    message = _render("security.risky_service", {"device_id": "d", "risk": "high", "ports": [
        {"port": 21, "proto": "tcp", "service": "ftp", "risk": "warning", "reason": "FTP sends passwords in clear text"},
        {"port": 23, "proto": "tcp", "service": "telnet", "risk": "high", "reason": "Telnet sends passwords in clear text"},
    ]}, name="CAM")
    assert message.title == "Risky services on CAM"
    assert message.body == ("21/tcp ftp: FTP sends passwords in clear text\n"
                            "23/tcp telnet: Telnet sends passwords in clear text")


def test_guest_messages():
    added = _render("guest.added", {"name": "Anna phone", "expires_at": "2026-10-05T10:00:00+00:00"}, name="Anna phone")
    assert (added.title, added.body, added.priority) == ("Guest added", "Guest Anna phone added (expires 05/10 12:00)", 3)
    forever = _render("guest.added", {"name": "Bo"}, name="Bo")
    assert forever.body == "Guest Bo added (no expiry)"
    expired = _render("guest.expired", {"name": "Bo", "mac": "00:00:5E:00:53:40", "last_ip": "192.168.1.9"})
    assert (expired.title, expired.body, expired.priority) == ("Guest expired", "Guest Bo expired and was removed", 2)
    removed = _render("guest.removed", {"name": "Bo"})
    assert (removed.title, removed.body) == ("Guest removed", "Guest Bo removed")
