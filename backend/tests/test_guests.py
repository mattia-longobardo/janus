# backend/tests/test_guests.py
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import guests
from app.models import Access, Device

ROME = ZoneInfo("Europe/Rome")
NOW = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)   # 12:00 a Roma


def test_date_means_end_of_that_day_in_local_time():
    assert guests.resolve_expiry(now=NOW, tz=ROME, expires_on=date(2026, 10, 3)) == datetime(2026, 10, 3, 21, 59, 59, tzinfo=UTC)


def test_duration_and_past_values():
    assert guests.resolve_expiry(now=NOW, tz=ROME, expires_in_hours=2) == NOW + timedelta(hours=2)
    with pytest.raises(guests.GuestError, match="expiry"):
        guests.resolve_expiry(now=NOW, tz=ROME, expires_on=date(2026, 10, 2))
    with pytest.raises(guests.GuestError, match="expiry"):
        guests.resolve_expiry(now=NOW, tz=ROME, expires_in_hours=0)
    with pytest.raises(guests.GuestError, match="only one"):
        guests.resolve_expiry(now=NOW, tz=ROME, expires_in_hours=1, expires_on=date(2026, 10, 4))
    assert guests.resolve_expiry(now=NOW, tz=ROME) is None


def test_own_expiry_beats_the_global_rule():
    d = Device(mac="00:00:5E:00:53:40", name="Phone", hostname="phone", access=Access.guest,
               guest_since=NOW, guest_expires_at=NOW + timedelta(days=3))
    assert guests.effective_expiry(d, 24, 6) == (NOW + timedelta(days=3), "device")   # own expiry beats both rules
    d.guest_expires_at = None
    assert guests.effective_expiry(d, 24, None) == (NOW + timedelta(hours=24), "global")
    assert guests.effective_expiry(d, None, None) == (None, None)


def test_inactivity_counts_from_last_seen_and_first_rule_wins():
    d = Device(mac="00:00:5E:00:53:47", name="Phone", hostname="phone2", access=Access.guest, guest_since=NOW)
    assert guests.effective_expiry(d, 24, 6) == (NOW + timedelta(hours=6), "inactive")      # never seen: from guest_since
    d.last_seen = NOW + timedelta(hours=20)
    assert guests.effective_expiry(d, 24, 6) == (NOW + timedelta(hours=24), "global")       # still active, 24 h rule first
    assert guests.effective_expiry(d, None, 6) == (NOW + timedelta(hours=26), "inactive")


def test_inactive_guest_is_due_even_if_recently_added(db):
    guests.SETTINGS.update(db, {"inactive_remove_hours": 6})
    idle = guests.add_by_mac(db, "00:00:5E:00:53:48", "Idle", None, NOW - timedelta(hours=10))
    idle.last_seen = NOW - timedelta(hours=7)
    busy = guests.add_by_mac(db, "00:00:5E:00:53:49", "Busy", None, NOW - timedelta(hours=10))
    busy.last_seen = NOW - timedelta(minutes=5)
    db.flush()
    assert [d.id for d in guests.expired(db, NOW)] == [idle.id]


def test_expired_lists_only_due_guests(db):
    guests.SETTINGS.update(db, {"auto_remove_hours": 24})
    old = guests.add_by_mac(db, "00:00:5E:00:53:41", "Old phone", None, NOW - timedelta(hours=25))
    guests.add_by_mac(db, "00:00:5E:00:53:42", "New phone", None, NOW - timedelta(hours=1))
    guests.add_by_mac(db, "00:00:5E:00:53:43", "Long stay", NOW + timedelta(days=2), NOW - timedelta(hours=30))
    assert [d.id for d in guests.expired(db, NOW)] == [old.id]


def test_adding_by_mac_creates_a_guest_without_ip_or_group(db):
    d = guests.add_by_mac(db, "00:00:5E:00:53:44", "Tablet", None, NOW)
    assert (d.access, d.static_ip, d.group_id, d.guest_since) == (Access.guest, None, None, NOW)


def test_a_pending_mac_is_admitted_but_an_approved_one_is_refused(db):
    pending = Device(mac="00:00:5E:00:53:45", name="Unknown 53:45", hostname="unknown-53-45", access=Access.pending,
                     static_ip=None)
    approved = Device(mac="00:00:5E:00:53:46", name="Laptop", hostname="laptop", access=Access.authorized,
                      static_ip="192.168.1.12")
    db.add_all([pending, approved])
    db.flush()
    assert guests.add_by_mac(db, "00:00:5E:00:53:45", "Guest tablet", None, NOW).id == pending.id
    with pytest.raises(guests.GuestError, match="already a authorized device"):
        guests.add_by_mac(db, "00:00:5E:00:53:46", "Again", None, NOW)
