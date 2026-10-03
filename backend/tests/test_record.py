from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.models import Access, Device, Event, Group, Sighting
from app.net.ipplan import NetworkPlan
from app.sentinel.observe import Observation
from app.sentinel.record import record_observation

PLAN = NetworkPlan.from_settings(Settings())
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
KNOWN = "00:00:5E:00:53:10"


def _events(db, kind):
    return list(db.scalars(select(Event).where(Event.type == kind).order_by(Event.id)))


def _record(db, mac, ip, source="arp", at=NOW, **extra):
    return record_observation(db, Observation(mac, ip, source, **extra), PLAN, at)


@pytest.fixture
def known(db):
    group = Group(name="People", color="#6FB7FF", icon="device", range_start="192.168.1.10",
                  range_end="192.168.1.19", default_access=Access.authorized)
    device = Device(mac=KNOWN, name="LAPTOP_A", hostname="laptop-a", group=group, static_ip="192.168.1.10",
                    access=Access.authorized, dhcp_hostname="laptop-a")
    db.add_all([group, device])
    db.flush()
    return device


def test_known_device_is_marked_online_and_sighted(db, known):
    _record(db, KNOWN, "192.168.1.10")
    assert (known.online, known.last_seen, known.first_seen, known.last_ip) == (True, NOW, NOW, "192.168.1.10")
    assert db.scalar(select(func.count()).select_from(Sighting)) == 1
    assert _events(db, "device.new") == []


def test_repeated_sightings_are_thinned(db, known):
    for minutes in (0, 1, 2, 13):
        _record(db, KNOWN, "192.168.1.10", at=NOW + timedelta(minutes=minutes))
    _record(db, KNOWN, "192.168.1.10", source="dhcp", at=NOW + timedelta(minutes=14))
    assert db.scalar(select(func.count()).select_from(Sighting)) == 3


def test_unknown_mac_becomes_pending_with_event(db):
    device = _record(db, "00:00:5E:00:53:40", "192.168.1.243", source="dhcp", hostname="pixel-7",
                     vendor_class="android-dhcp-14", param_list=(1, 3, 6))
    assert (device.access, device.group_id, device.name, device.hostname) == (Access.pending, None, "pixel-7", "pixel-7")
    [event] = _events(db, "device.new")
    assert event.mac == "00:00:5E:00:53:40"
    assert event.payload == {"device_id": str(device.id), "ip": "192.168.1.243", "hostname": "pixel-7",
                             "private_mac": False, "source": "dhcp"}
    assert db.scalar(select(Sighting.payload)) == {"hostname": "pixel-7", "vendor_class": "android-dhcp-14",
                                                   "param_list": [1, 3, 6]}
    _record(db, "00:00:5E:00:53:40", "192.168.1.243", at=NOW + timedelta(minutes=1))
    assert len(_events(db, "device.new")) == 1


def test_unknown_without_hostname_gets_placeholder_name(db):
    device = _record(db, "00:00:5E:00:53:41", None)
    assert (device.name, device.hostname, device.last_ip) == ("Unknown 00:53:41", "unknown-00-53-41", None)


def test_gateway_is_registered_without_alert(db):
    device = _record(db, "00:00:5E:00:53:01", "192.168.1.1")
    assert (device.name, device.access, device.static_ip, device.group_id) == ("Gateway", Access.authorized, None, None)
    assert _events(db, "device.new") == []
    assert len(_events(db, "device.gateway")) == 1


def test_private_mac_reusing_a_known_hostname_is_flagged(db, known):
    device = _record(db, "02:00:5E:00:53:50", "192.168.1.244", source="dhcp", hostname="laptop-a")
    assert device.private_mac is True
    [event] = _events(db, "device.private_mac")
    assert event.payload == {"device_id": str(device.id), "previous_mac": KNOWN, "previous_name": "LAPTOP_A"}
    assert _events(db, "device.new")[0].payload["private_mac"] is True


def test_ip_conflict_detected_once_per_hour(db, known):
    other = "00:00:5E:00:53:60"
    _record(db, KNOWN, "192.168.1.10")
    _record(db, other, "192.168.1.10", at=NOW + timedelta(seconds=30))
    _record(db, other, "192.168.1.10", at=NOW + timedelta(seconds=60))
    assert _events(db, "ip.conflict") == []
    _record(db, KNOWN, "192.168.1.10", at=NOW + timedelta(seconds=90))
    [event] = _events(db, "ip.conflict")
    assert event.payload["ip"] == "192.168.1.10"
    assert event.payload["macs"] == [KNOWN, other]
    assert (event.payload["owner"]["mac"], event.payload["claimant"]["mac"], event.payload["reserved"]) == (KNOWN, other, True)
    assert event.mac == other
    later = NOW + timedelta(hours=2)
    _record(db, KNOWN, "192.168.1.10", at=later)
    _record(db, other, "192.168.1.10", at=later + timedelta(seconds=30))
    assert len(_events(db, "ip.conflict")) == 2


def test_no_conflict_when_previous_owner_is_stale(db, known):
    _record(db, KNOWN, "192.168.1.10")
    _record(db, "00:00:5E:00:53:60", "192.168.1.10", at=NOW + timedelta(minutes=5))
    assert _events(db, "ip.conflict") == []


def test_ip_mismatch_for_approved_device(db, known):
    _record(db, KNOWN, "192.168.1.17")
    assert _events(db, "device.ip_mismatch") == []
    _record(db, KNOWN, "192.168.1.17", at=NOW + timedelta(minutes=1))
    [event] = _events(db, "device.ip_mismatch")
    assert event.payload == {"device_id": str(known.id), "name": "LAPTOP_A", "ip": "192.168.1.17",
                             "expected": "192.168.1.10"}
    _record(db, KNOWN, "192.168.1.17", at=NOW + timedelta(minutes=10))
    _record(db, KNOWN, "192.168.1.245", at=NOW + timedelta(minutes=20))
    assert len(_events(db, "device.ip_mismatch")) == 1


def test_second_mac_claiming_the_gateway_is_pending(db):
    _record(db, "00:00:5E:00:53:01", "192.168.1.1")
    spoof = _record(db, "00:00:5E:00:53:66", "192.168.1.1", at=NOW + timedelta(minutes=5))
    assert spoof.access is Access.pending
    assert [e.mac for e in _events(db, "device.new")] == ["00:00:5E:00:53:66"]


def test_ip_mismatch_repeats_only_daily_for_the_same_address(db, known):
    _record(db, KNOWN, "192.168.1.17")
    _record(db, KNOWN, "192.168.1.17", at=NOW + timedelta(minutes=1))
    _record(db, KNOWN, "192.168.1.17", at=NOW + timedelta(hours=2))
    assert len(_events(db, "device.ip_mismatch")) == 1
    _record(db, KNOWN, "192.168.1.18", at=NOW + timedelta(hours=3))
    _record(db, KNOWN, "192.168.1.18", at=NOW + timedelta(hours=3, minutes=1))
    assert len(_events(db, "device.ip_mismatch")) == 2
    _record(db, KNOWN, "192.168.1.18", at=NOW + timedelta(hours=28))
    assert len(_events(db, "device.ip_mismatch")) == 3


def test_mdns_hostname_does_not_replace_dhcp_hostname(db, known):
    _record(db, KNOWN, "192.168.1.10", source="mdns", hostname="laptop-a-mdns")
    assert known.dhcp_hostname == "laptop-a"


def test_rich_sightings_are_thinned(db, known):
    for minutes in (0, 1, 2):
        _record(db, KNOWN, "192.168.1.10", source="mdns", at=NOW + timedelta(minutes=minutes), services=("_ssh._tcp",))
    _record(db, KNOWN, "192.168.1.10", source="mdns", at=NOW + timedelta(minutes=3), services=("_smb._tcp",))
    _record(db, KNOWN, "192.168.1.10", source="mdns", at=NOW + timedelta(hours=7), services=("_smb._tcp",))
    assert db.scalar(select(func.count()).select_from(Sighting).where(Sighting.source == "mdns")) == 3


def test_alternating_mdns_subsets_do_not_write_every_packet(db, known):
    variants = [{"hostname": "laptop-a"}, {"services": ("_ssh._tcp",)}, {"model": "MacBookPro18,3"}]
    for minute in range(12):
        _record(db, KNOWN, "192.168.1.10", source="mdns", at=NOW + timedelta(minutes=minute), **variants[minute % 3])
    assert db.scalar(select(func.count()).select_from(Sighting).where(Sighting.source == "mdns")) == 3
    _record(db, KNOWN, "192.168.1.10", source="mdns", at=NOW + timedelta(minutes=13), services=("_ssh._tcp", "_smb._tcp"))
    assert db.scalar(select(func.count()).select_from(Sighting).where(Sighting.source == "mdns")) == 4


def test_link_local_and_boot_blips_never_raise_a_mismatch(db, known):
    _record(db, KNOWN, "169.254.191.63")
    _record(db, KNOWN, "169.254.191.63", at=NOW + timedelta(minutes=1))
    assert known.last_ip != "169.254.191.63"
    _record(db, KNOWN, "192.168.1.10", at=NOW + timedelta(minutes=2))
    _record(db, KNOWN, "192.168.1.30", at=NOW + timedelta(minutes=3))
    _record(db, KNOWN, "192.168.1.10", at=NOW + timedelta(minutes=4))
    assert _events(db, "device.ip_mismatch") == []
    assert known.last_ip == "192.168.1.10"


def test_dhcp_handover_is_not_a_conflict(db, known):
    previous_holder = "00:00:5E:00:53:61"
    _record(db, previous_holder, "192.168.1.10")
    _record(db, KNOWN, "192.168.1.50", at=NOW - timedelta(minutes=5))
    _record(db, KNOWN, "192.168.1.10", at=NOW + timedelta(seconds=20))
    _record(db, KNOWN, "192.168.1.10", at=NOW + timedelta(seconds=80))
    _record(db, previous_holder, "192.168.1.31", at=NOW + timedelta(seconds=100))
    assert _events(db, "ip.conflict") == []


def test_conflict_names_the_reservation_owner_even_when_it_answers_second(db, known):
    other = "00:00:5E:00:53:61"
    _record(db, other, "192.168.1.10")
    _record(db, KNOWN, "192.168.1.10", at=NOW + timedelta(seconds=30))
    _record(db, other, "192.168.1.10", at=NOW + timedelta(seconds=60))
    [event] = _events(db, "ip.conflict")
    assert event.payload["owner"]["name"] == "LAPTOP_A"
    assert event.payload["claimant"]["mac"] == other
    assert event.payload["reserved"] is True


def test_guest_seen_at_any_ip_raises_no_mismatch(db):
    db.add(Device(mac="00:00:5E:00:53:62", name="Anna", hostname="anna", access=Access.guest, guest_since=NOW))
    db.flush()
    _record(db, "00:00:5E:00:53:62", "192.168.1.210")
    _record(db, "00:00:5E:00:53:62", "192.168.1.211", at=NOW + timedelta(minutes=10))
    _record(db, "00:00:5E:00:53:62", "192.168.1.211", at=NOW + timedelta(minutes=20))
    assert _events(db, "device.ip_mismatch") == [] and _events(db, "device.new") == []
