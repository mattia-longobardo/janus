from app.providers.base import CurrentEntry, Policy, Reservation
from app.providers.pihole.codec import LAN_ONLY_TAG, parse, render

PLAIN = Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10")
LAN = Reservation("00:00:5E:00:53:20", "plug", "192.168.1.120", Policy.LAN_ONLY)


def test_render_is_byte_identical_to_before():
    assert LAN_ONLY_TAG == "set:lanonly"
    assert render(PLAIN, "24h") == "00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"
    assert render(LAN, "24h") == "00:00:5e:00:53:20,set:lanonly,192.168.1.120,plug,24h"
    assert render(PLAIN, "12h") == "00:00:5e:00:53:10,192.168.1.10,laptop-a,12h"


def test_parse_round_trip():
    for r in (PLAIN, LAN):
        raw = render(r, "24h")
        assert parse(raw, "24h") == CurrentEntry(raw, raw, r.mac, r.ip, r, canonical=True)


def test_parse_normalizes_mac_and_spacing_like_before():
    raw = "00-00-5E-00-53-10, 192.168.1.10, laptop-a, 24h"
    entry = parse(raw, "24h")
    assert entry.reservation == PLAIN and entry.mac == "00:00:5E:00:53:10" and entry.ip == "192.168.1.10"
    assert entry.key == entry.display == raw


def test_canonical_means_the_configured_lease():
    # The diff keeps a line whose fields equal the desired reservation whatever the raw text looks like
    # (ruling R21); only a different lease makes Janus rewrite it.
    assert parse("00:00:5E:00:53:20,set:lanonly,192.168.1.120,plug,24h", "24h").canonical is True
    stale = parse("00:00:5e:00:53:20,set:lanonly,192.168.1.120,plug,12h", "24h")
    assert stale.canonical is False and stale.reservation == LAN


def test_unreadable_lines_still_expose_mac_and_ip():
    stranger = parse("not,a,reservation", "24h")
    assert (stranger.reservation, stranger.mac, stranger.ip, stranger.key) == (None, None, None, "not,a,reservation")
    manual = parse("00:00:5E:00:53:99,192.168.1.200,someone-elses-nas", "24h")
    assert manual.reservation is None
    assert (manual.mac, manual.ip) == ("00:00:5E:00:53:99", "192.168.1.200")
    bad_mac = parse("zz:zz,192.168.1.5,x,24h", "24h")
    assert (bad_mac.reservation, bad_mac.mac, bad_mac.ip) == (None, None, "192.168.1.5")


def test_duplicate_guard_uses_the_line_identity_not_the_raw_ip_field():
    # Ruling R22: like _identity() before the refactor, whatever field holds the address.
    swapped = parse("00:00:5e:00:53:99,nas,192.168.1.5,24h", "24h")
    assert swapped.reservation is not None and swapped.reservation.ip == "nas"
    assert (swapped.mac, swapped.ip) == ("00:00:5E:00:53:99", "192.168.1.5")
    assert swapped.mac == swapped.reservation.mac
    # Python's IPv4Address rejects leading zeros, so before the refactor this line held no IP either.
    padded = parse("00:00:5e:00:53:99,192.168.1.005,nas,24h", "24h")
    assert (padded.mac, padded.ip) == ("00:00:5E:00:53:99", None)


def test_diff_refuses_an_addition_on_the_ip_of_a_swapped_line():
    from app.enforcement.reservations import diff_reservations
    current = [parse("00:00:5e:00:53:99,nas,192.168.1.5,24h", "24h")]
    wanted = Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.5")
    diff = diff_reservations({wanted}, current, {"00:00:5E:00:53:10"}, lambda r: render(r, "24h"))
    assert diff.to_add == [] and diff.unmanaged == current
    assert diff.failed == ["00:00:5e:00:53:10,192.168.1.5,laptop-a,24h: would duplicate "
                           "00:00:5e:00:53:99,nas,192.168.1.5,24h, skipped"]
