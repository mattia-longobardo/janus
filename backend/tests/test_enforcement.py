import pytest
from sqlalchemy import select

from app.enforcement.reservations import desired_reservations, diff_reservations, managed_macs, written_macs
from app.enforcement.sync import apply_sync, plan_sync
from app.models import Access, Device, Event, Group, Setting
from app.providers.base import CurrentEntry, LeaseControl, Policy, ProviderError, Reservation, ReservationStore
from tests.fakes_provider import FakeStore

ALL = frozenset(Policy)
DHCP_ONLY = frozenset({Policy.FULL, Policy.LAN_ONLY})


def _group(db, name="People", start="192.168.1.10", end="192.168.1.19"):
    g = Group(name=name, color="#6FB7FF", icon="device", range_start=start, range_end=end, default_access=Access.authorized)
    db.add(g)
    db.flush()
    return g


def _device(db, group, name, mac, ip, access=Access.authorized):
    d = Device(mac=mac, name=name, hostname=name.lower().replace("_", "-"), group=group, static_ip=ip, access=access)
    db.add(d)
    db.flush()
    return d


def _entry(mac, ip, host, policy=Policy.FULL, *, canonical=True, key=None):
    r = Reservation(mac, host, ip, policy)
    return CurrentEntry(key or f"{mac},{ip},{host}", key or f"{mac},{ip},{host}", mac, ip, r, canonical)


def _foreign(mac, ip, text):
    """An entry Janus cannot read as one of its reservations (manual line, other tool)."""
    return CurrentEntry(text, text, mac, ip, None)


def _own(store, r):
    """The entry FakeStore holds for a reservation Janus wrote."""
    key = store.describe(r)
    return CurrentEntry(key, key, r.mac, r.ip, r)


def test_fake_store_implements_the_protocols():
    assert isinstance(FakeStore(), ReservationStore) and isinstance(FakeStore(), LeaseControl)


def test_desired_maps_access_to_policy_and_drops_unsupported(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    _device(db, g, "PLUG", "00:00:5E:00:53:20", "192.168.1.11", Access.lan_only)
    _device(db, g, "BAD", "00:00:5E:00:53:30", None, Access.blocked)
    assert desired_reservations(db, ALL) == {
        Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10", Policy.FULL),
        Reservation("00:00:5E:00:53:20", "plug", "192.168.1.11", Policy.LAN_ONLY),
        Reservation("00:00:5E:00:53:30", "bad", None, Policy.BLOCKED),
    }
    assert {r.policy for r in desired_reservations(db, frozenset({Policy.FULL}))} == {Policy.FULL}


def test_desired_only_includes_approved_devices_with_mac_and_ip(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    _device(db, g, "PLUG", "00:00:5E:00:53:20", "192.168.1.11", Access.lan_only)
    _device(db, g, "PENDING", "00:00:5E:00:53:21", "192.168.1.12", Access.pending)
    _device(db, g, "BLOCKED", "00:00:5E:00:53:22", "192.168.1.13", Access.blocked)
    _device(db, g, "NO_MAC", None, "192.168.1.14")
    _device(db, g, "NO_IP", "00:00:5E:00:53:23", None)
    assert desired_reservations(db, DHCP_ONLY) == {
        Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10"),
        Reservation("00:00:5E:00:53:20", "plug", "192.168.1.11", Policy.LAN_ONLY),
    }


def test_blocked_reservation_needs_a_mac_but_no_ip(db):
    g = _group(db)
    _device(db, g, "BANNED", "00:00:5E:00:53:22", "192.168.1.13", Access.blocked)
    _device(db, g, "NO_MAC", None, None, Access.blocked)
    assert desired_reservations(db, ALL) == {Reservation("00:00:5E:00:53:22", "banned", None, Policy.BLOCKED)}


def test_diff_adds_missing_and_removes_stale():
    keep = Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10")
    new = Reservation("00:00:5E:00:53:11", "phone-a", "192.168.1.11")
    stale = _entry("00:00:5E:00:53:12", "192.168.1.12", "old")
    diff = diff_reservations({keep, new}, [_entry(keep.mac, keep.ip, keep.hostname), stale])
    assert diff.to_add == [new]
    assert diff.to_remove == [stale]
    assert not diff.empty


def test_diff_detects_ip_change_as_remove_plus_add():
    before = _entry("00:00:5E:00:53:10", "192.168.1.10", "laptop-a")
    after = Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.13")
    diff = diff_reservations({after}, [before])
    assert diff.to_add == [after] and diff.to_remove == [before]


def test_diff_detects_policy_change_as_remove_plus_add():
    before = _entry("00:00:5E:00:53:10", "192.168.1.10", "laptop-a")
    after = Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10", Policy.LAN_ONLY)
    diff = diff_reservations({after}, [before])
    assert diff.to_add == [after] and diff.to_remove == [before] and diff.failed == []


def test_diff_keeps_unreadable_entries():
    garbage = _foreign(None, None, "this is not a reservation")
    diff = diff_reservations(set(), [garbage])
    assert diff.unmanaged == [garbage]
    assert diff.to_remove == []
    assert diff.empty


def test_unmanaged_entries_are_reported_never_removed(db):
    stranger = _entry("00:00:5E:00:53:99", "192.168.1.99", "nas")
    diff = diff_reservations(set(), [stranger], managed=set())
    assert diff.to_remove == [] and diff.unmanaged == [stranger]


def test_duplicate_ip_with_unmanaged_entry_is_refused(db):
    stranger = _entry("00:00:5E:00:53:99", "192.168.1.10", "nas")
    want = Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10")
    diff = diff_reservations({want}, [stranger], managed=set())
    assert diff.to_add == [] and "would duplicate" in diff.failed[0]


def test_duplicate_mac_with_unmanaged_entry_is_refused():
    stranger = _foreign("00:00:5E:00:53:10", "192.168.1.99", "00:00:5E:00:53:10,192.168.1.99,manual")
    want = Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10")
    diff = diff_reservations({want}, [stranger], managed=set(), describe=lambda r: f"line {r.hostname}")
    assert diff.to_add == []
    assert diff.failed == ["line laptop-a: would duplicate 00:00:5E:00:53:10,192.168.1.99,manual, skipped"]


def test_duplicate_within_the_additions_is_refused():
    a = Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10")
    b = Reservation("00:00:5E:00:53:11", "laptop-b", "192.168.1.10")
    diff = diff_reservations({a, b}, [], describe=lambda r: r.hostname)
    assert diff.to_add == [a] and diff.failed == ["laptop-b: would duplicate laptop-a, skipped"]


def test_reservations_without_ip_never_clash_on_ip():
    blocked = Reservation("00:00:5E:00:53:22", "banned", None, Policy.BLOCKED)
    other = _foreign("00:00:5E:00:53:99", None, "guest pass")
    diff = diff_reservations({blocked}, [other], managed=set())
    assert diff.to_add == [blocked] and diff.failed == []


def test_non_canonical_own_entry_is_rewritten(db):
    want = Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10")
    old = _entry("00:00:5E:00:53:10", "192.168.1.10", "laptop-a", canonical=False, key="old-format")
    diff = diff_reservations({want}, [old], managed={"00:00:5E:00:53:10"})
    assert [e.key for e in diff.to_remove] == ["old-format"] and diff.to_add == [want]


def test_as_dict_uses_describe_and_display():
    want = Reservation("00:00:5E:00:53:11", "phone-a", "192.168.1.11")
    stale = _entry("00:00:5E:00:53:12", "192.168.1.12", "old")
    stranger = _foreign(None, None, "garbage")
    diff = diff_reservations({want}, [stale, stranger], managed={"00:00:5E:00:53:12"})
    assert diff.as_dict(lambda r: f"<{r.hostname}>") == {
        "to_add": ["<phone-a>"],
        "to_remove": ["00:00:5E:00:53:12,192.168.1.12,old"],
        "unmanaged": ["garbage"],
        "failed": [],
    }


def test_written_macs_are_per_provider(db):
    store = FakeStore([_entry("00:00:5E:00:53:10", "192.168.1.10", "laptop-a")])
    managed_macs(db, "pihole", store.list_reservations())
    assert written_macs(db, "pihole") == {"00:00:5E:00:53:10"}
    assert written_macs(db, "unifi") is None
    assert db.get(Setting, "provider.pihole.written_macs").value == ["00:00:5E:00:53:10"]


def test_plan_sync_never_writes(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    store = FakeStore()
    diff = plan_sync(db, store, "fake", ALL)
    assert diff.to_add == [Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10")]
    assert store.writes == []


def test_apply_sync_removes_before_adding_and_logs(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.13")
    store = FakeStore()
    old = _own(store, Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10"))
    store.entries = [old]
    apply_sync(db, store, "fake", ALL)
    assert store.writes == [
        ("remove", "00:00:5E:00:53:10,192.168.1.10,laptop-a,full"),
        ("add", "00:00:5E:00:53:10,192.168.1.13,laptop-a,full"),
    ]
    event = db.scalar(select(Event).where(Event.type == "sync.applied"))
    assert event.payload == {"added": ["00:00:5E:00:53:10,192.168.1.13,laptop-a,full"],
                             "removed": ["00:00:5E:00:53:10,192.168.1.10,laptop-a,full"]}
    assert apply_sync(db, store, "fake", ALL).empty


def test_apply_records_rejections_and_keeps_going(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    _device(db, g, "LAPTOP_B", "00:00:5E:00:53:11", "192.168.1.11")
    store = FakeStore(reject={"00:00:5E:00:53:10"})
    diff = apply_sync(db, store, "fake", ALL)
    assert len(diff.failed) == 1 and [w[0] for w in store.writes] == ["add"]


def test_apply_sync_skips_rejected_entry_and_continues(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    _device(db, g, "PHONE_A", "00:00:5E:00:53:11", "192.168.1.11")
    bad = "00:00:5E:00:53:10,192.168.1.10,laptop-a,full"
    store = FakeStore(reject={"00:00:5E:00:53:10"})
    diff = apply_sync(db, store, "fake", ALL)
    assert [e.key for e in store.entries] == ["00:00:5E:00:53:11,192.168.1.11,phone-a,full"]
    assert len(diff.failed) == 1 and diff.failed[0].startswith(bad)
    failed = db.scalar(select(Event).where(Event.type == "sync.failed"))
    assert failed.payload["failed"] == diff.failed
    applied = db.scalar(select(Event).where(Event.type == "sync.applied"))
    assert applied.payload == {"added": ["00:00:5E:00:53:11,192.168.1.11,phone-a,full"], "removed": []}
    assert written_macs(db, "fake") == {"00:00:5E:00:53:11"}


def test_apply_sync_logs_partial_progress_before_transport_error(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.13")
    stale = _entry("00:00:5E:00:53:10", "192.168.1.10", "laptop-a")
    store = FakeStore([stale], drop_after_writes=1)
    with pytest.raises(ProviderError):
        apply_sync(db, store, "fake", ALL)
    applied = db.scalar(select(Event).where(Event.type == "sync.applied"))
    assert applied.payload == {"added": [], "removed": [stale.display]}
    assert db.scalar(select(Event).where(Event.type == "sync.failed")) is None


def test_apply_sync_records_additions_before_transport_error(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    _device(db, g, "LAPTOP_B", "00:00:5E:00:53:11", "192.168.1.11")
    store = FakeStore(drop_after_writes=1)
    with pytest.raises(ProviderError):
        apply_sync(db, store, "fake", ALL)
    assert written_macs(db, "fake") == {"00:00:5E:00:53:10"}
    applied = db.scalar(select(Event).where(Event.type == "sync.applied"))
    assert applied.payload == {"added": ["00:00:5E:00:53:10,192.168.1.10,laptop-a,full"], "removed": []}


def test_foreign_entries_are_reported_not_removed(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    _device(db, g, "BANNED", "00:00:5E:00:53:22", "192.168.1.13", Access.blocked)
    foreign = _foreign("00:00:5E:00:53:99", "192.168.1.200", "00:00:5E:00:53:99,192.168.1.200,someone-elses-nas")
    blocked = _entry("00:00:5E:00:53:22", "192.168.1.13", "banned")
    store = FakeStore([_entry("00:00:5E:00:53:10", "192.168.1.10", "laptop-a"), foreign, blocked])
    diff = plan_sync(db, store, "fake", DHCP_ONLY)
    assert diff.to_remove == [blocked]
    assert diff.unmanaged == [foreign]
    apply_sync(db, store, "fake", DHCP_ONLY)
    assert foreign in store.entries and blocked not in store.entries


def test_deleted_device_reservation_is_removed_before_its_ip_is_reused(db):
    g = _group(db)
    old = _device(db, g, "A53_CINZIA", "00:00:5E:00:53:61", "192.168.1.11")
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    store = FakeStore([])
    apply_sync(db, store, "fake", ALL)
    assert "00:00:5E:00:53:61,192.168.1.11,a53-cinzia,full" in [e.key for e in store.entries]
    db.delete(old)
    db.flush()
    _device(db, g, "PHONE_CINZIA", "00:00:5E:00:53:62", "192.168.1.11")
    diff = apply_sync(db, store, "fake", ALL)
    assert diff.failed == []
    assert sorted(e.key for e in store.entries) == ["00:00:5E:00:53:10,192.168.1.10,laptop-a,full",
                                                    "00:00:5E:00:53:62,192.168.1.11,phone-cinzia,full"]
    assert [kind for kind, _ in store.writes[-2:]] == ["remove", "add"]


def test_addition_that_would_duplicate_an_ip_is_skipped_not_written(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    manual = _foreign("00:00:5E:00:53:99", "192.168.1.10", "00:00:5E:00:53:99,192.168.1.10,someone-elses-nas")
    store = FakeStore([manual])
    diff = apply_sync(db, store, "fake", ALL)
    assert store.entries == [manual] and store.writes == []
    assert len(diff.failed) == 1 and "would duplicate" in diff.failed[0]
    assert diff.failed[0].startswith("00:00:5E:00:53:10,192.168.1.10,laptop-a,full: would duplicate " + manual.display)


def test_existing_janus_entries_are_recognised_on_first_run(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    gone = _entry("00:00:5E:00:53:44", "192.168.1.14", "old-phone")
    manual = _entry("00:00:5E:00:53:99", "192.168.1.200", "nas", canonical=False)
    store = FakeStore([_entry("00:00:5E:00:53:10", "192.168.1.10", "laptop-a"), gone, manual])
    diff = plan_sync(db, store, "fake", ALL)
    assert diff.to_remove == [gone]
    assert diff.unmanaged == [manual]
    assert written_macs(db, "fake") == {"00:00:5E:00:53:10", "00:00:5E:00:53:44"}


def test_recorded_written_macs_replace_first_run_recognition(db):
    store = FakeStore([_entry("00:00:5E:00:53:44", "192.168.1.14", "old-phone")])
    db.add(Setting(key="provider.fake.written_macs", value=[]))
    db.flush()
    diff = plan_sync(db, store, "fake", ALL)
    assert diff.to_remove == [] and [e.mac for e in diff.unmanaged] == ["00:00:5E:00:53:44"]
