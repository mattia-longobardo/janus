import pytest
from sqlalchemy import select

from app.models import Access, Device, Event, Group
from app.pihole.reservations import HostLine, desired_hosts, diff_hosts
from app.pihole.sync import apply_sync, plan_sync
from app.providers.pihole.client import PiholeError
from tests.fakes import FakePihole


def _group(db, name="People", start="192.168.1.10", end="192.168.1.19"):
    g = Group(name=name, color="#6FB7FF", icon="device", range_start=start, range_end=end,
              default_access=Access.authorized)
    db.add(g)
    db.flush()
    return g


def _device(db, group, name, mac, ip, access=Access.authorized):
    d = Device(mac=mac, name=name, hostname=name.lower().replace("_", "-"), group=group, static_ip=ip, access=access)
    db.add(d)
    db.flush()
    return d


def test_desired_hosts_only_include_approved_devices_with_mac_and_ip(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    _device(db, g, "PLUG", "00:00:5E:00:53:20", "192.168.1.11", Access.lan_only)
    _device(db, g, "PENDING", "00:00:5E:00:53:21", "192.168.1.12", Access.pending)
    _device(db, g, "BLOCKED", "00:00:5E:00:53:22", "192.168.1.13", Access.blocked)
    _device(db, g, "NO_MAC", None, "192.168.1.14")
    _device(db, g, "NO_IP", "00:00:5E:00:53:23", None)
    assert desired_hosts(db, "24h") == {
        HostLine("00:00:5E:00:53:10", "192.168.1.10", "laptop-a"),
        HostLine("00:00:5E:00:53:20", "192.168.1.11", "plug", lan_only=True),
    }


def test_diff_adds_missing_and_removes_stale():
    keep = HostLine("00:00:5E:00:53:10", "192.168.1.10", "laptop-a")
    new = HostLine("00:00:5E:00:53:11", "192.168.1.11", "phone-a")
    stale = "00:00:5e:00:53:12,192.168.1.12,old,24h"
    diff = diff_hosts({keep, new}, [keep.render(), stale])
    assert diff.to_add == [new]
    assert diff.to_remove == [stale]
    assert not diff.empty


def test_diff_detects_ip_change_as_remove_plus_add():
    before = "00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"
    after = HostLine("00:00:5E:00:53:10", "192.168.1.13", "laptop-a")
    diff = diff_hosts({after}, [before])
    assert diff.to_add == [after] and diff.to_remove == [before]


def test_diff_keeps_unmanaged_lines():
    garbage = "this is not a reservation"
    diff = diff_hosts(set(), [garbage])
    assert diff.unmanaged == [garbage]
    assert diff.to_remove == []
    assert diff.empty


def test_plan_sync_never_writes(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    fake = FakePihole()
    diff = plan_sync(db, fake, "24h")
    assert [h.render() for h in diff.to_add] == ["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"]
    assert fake.writes == []


def test_apply_sync_removes_before_adding_and_logs(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.13")
    fake = FakePihole(["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"])
    apply_sync(db, fake, "24h")
    assert fake.writes == [
        ("remove", "00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"),
        ("add", "00:00:5e:00:53:10,192.168.1.13,laptop-a,24h"),
    ]
    event = db.scalar(select(Event).where(Event.type == "sync.applied"))
    assert event.payload["added"] == ["00:00:5e:00:53:10,192.168.1.13,laptop-a,24h"]
    assert apply_sync(db, fake, "24h").empty


def test_apply_sync_skips_rejected_line_and_continues(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    _device(db, g, "PHONE_A", "00:00:5E:00:53:11", "192.168.1.11")
    bad = "00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"
    fake = FakePihole(reject={bad})
    diff = apply_sync(db, fake, "24h")
    assert fake.hosts == ["00:00:5e:00:53:11,192.168.1.11,phone-a,24h"]
    assert len(diff.failed) == 1 and diff.failed[0].startswith(bad)
    failed = db.scalar(select(Event).where(Event.type == "sync.failed"))
    assert failed.payload["failed"] == diff.failed
    applied = db.scalar(select(Event).where(Event.type == "sync.applied"))
    assert applied.payload == {"added": ["00:00:5e:00:53:11,192.168.1.11,phone-a,24h"], "removed": []}


def test_apply_sync_logs_partial_progress_before_transport_error(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.13")
    stale = "00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"
    fake = FakePihole([stale], drop_after_writes=1)
    with pytest.raises(PiholeError):
        apply_sync(db, fake, "24h")
    applied = db.scalar(select(Event).where(Event.type == "sync.applied"))
    assert applied.payload == {"added": [], "removed": [stale]}


def test_foreign_host_lines_are_reported_not_removed(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    _device(db, g, "BANNED", "00:00:5E:00:53:22", "192.168.1.13", Access.blocked)
    foreign = "00:00:5E:00:53:99,192.168.1.200,someone-elses-nas"
    blocked = "00:00:5e:00:53:22,192.168.1.13,banned,24h"
    fake = FakePihole(["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h", foreign, blocked])
    diff = plan_sync(db, fake, "24h")
    assert diff.to_remove == [blocked]
    assert diff.unmanaged == [foreign]
    apply_sync(db, fake, "24h")
    assert foreign in fake.hosts and blocked not in fake.hosts


def test_deleted_device_reservation_is_removed_before_its_ip_is_reused(db):
    g = _group(db)
    old = _device(db, g, "A53_CINZIA", "00:00:5E:00:53:61", "192.168.1.11")
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    fake = FakePihole([])
    apply_sync(db, fake, "24h")
    assert "00:00:5e:00:53:61,192.168.1.11,a53-cinzia,24h" in fake.hosts
    db.delete(old)
    db.flush()
    _device(db, g, "PHONE_CINZIA", "00:00:5E:00:53:62", "192.168.1.11")
    diff = apply_sync(db, fake, "24h")
    assert diff.failed == []
    assert sorted(fake.hosts) == ["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h",
                                  "00:00:5e:00:53:62,192.168.1.11,phone-cinzia,24h"]
    assert [kind for kind, _ in fake.writes[-2:]] == ["remove", "add"]


def test_addition_that_would_duplicate_an_ip_is_skipped_not_written(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    manual = "00:00:5E:00:53:99,192.168.1.10,someone-elses-nas"
    fake = FakePihole([manual])
    diff = apply_sync(db, fake, "24h")
    assert fake.hosts == [manual]
    assert len(diff.failed) == 1 and "would duplicate" in diff.failed[0]


def test_existing_janus_lines_are_recognised_on_first_run(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    gone = "00:00:5e:00:53:44,192.168.1.14,old-phone,24h"
    manual = "00:00:5E:00:53:99,192.168.1.200,nas"
    fake = FakePihole(["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h", gone, manual])
    diff = plan_sync(db, fake, "24h")
    assert diff.to_remove == [gone]
    assert diff.unmanaged == [manual]
