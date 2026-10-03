import json
from datetime import UTC, datetime, timedelta

import pytest
import respx

from app.config import settings
from app.models import Access, Device, Event, Group
from app.providers.pihole.cutover import QUARANTINE_LINES, PiholeAdmin, cutover, preflight, rollback, take_backup
from app.providers.pihole.provider import PiholeConfig
from app.syncmode import load_sync_mode
from tests.fakes import FakeAdmin

NOW = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)
BASE = "http://pihole.test"
CFG = PiholeConfig(url="http://192.168.1.220:1000", password="pw", lease="24h")


@pytest.fixture
def seeded(db, tmp_path, monkeypatch):
    monkeypatch.setenv("JANUS_BACKUP_DIR", str(tmp_path))
    group = Group(name="People", color="#6FB7FF", icon="device", range_start="192.168.1.10",
                  range_end="192.168.1.19", default_access=Access.authorized)
    db.add(group)
    db.flush()
    db.add(Device(mac="00:00:5E:00:53:10", name="LAPTOP_A", hostname="laptop-a", group=group,
                  static_ip="192.168.1.10", access=Access.authorized))
    db.flush()
    return tmp_path


def _checks(report):
    return {c.name: c.ok for c in report.checks}


def test_preflight_blocks_without_rules_and_backup(db, seeded):
    report = preflight(db, FakeAdmin(lines=()), CFG, dhcp_kind="pihole", now=NOW)
    checks = _checks(report)
    assert (checks["quarantine_rules"], checks["backup"], report.ready) == (False, False, False)
    assert checks["write_access"] is None
    assert report.plan == {"to_add": 1, "to_remove": 0, "unmanaged": 0}


def test_backup_then_green_preflight(db, seeded):
    admin = FakeAdmin()
    target = take_backup(db, admin, now=NOW - timedelta(hours=1))
    assert (target / "pihole-teleporter.zip").read_bytes().startswith(b"PK")
    dump = json.loads((target / "janus.json").read_text())
    assert [d["name"] for d in dump["devices"]] == ["LAPTOP_A"] and "sightings" not in dump
    report = preflight(db, admin, CFG, dhcp_kind="pihole", admin=admin)
    assert report.ready, report.as_dict()


def test_preflight_flags_incomplete_and_duplicate_devices(db, seeded):
    db.add_all([
        Device(mac=None, name="NO_MAC", hostname="no-mac", static_ip="192.168.1.11", access=Access.authorized),
        Device(mac="00:00:5e:00:53:10", name="TWIN", hostname="twin", static_ip="192.168.1.12", access=Access.authorized),
    ])
    db.flush()
    checks = _checks(preflight(db, FakeAdmin(), CFG, dhcp_kind="pihole", now=NOW))
    assert (checks["approved_devices_complete"], checks["no_duplicates"]) == (False, False)


def test_gateway_needs_no_reservation(db, seeded):
    db.add(Device(mac="00:00:5E:00:53:01", name="Gateway", hostname="gateway", last_ip="192.168.1.1",
                  access=Access.authorized))
    db.flush()
    assert _checks(preflight(db, FakeAdmin(), CFG, dhcp_kind="pihole", now=NOW))["approved_devices_complete"] is True


def test_unreachable_pihole_is_reported(db, seeded):
    checks = _checks(preflight(db, FakeAdmin(fail=True), CFG, dhcp_kind="pihole", now=NOW))
    assert checks["pihole_reachable"] is False


def test_cutover_writes_reservations_before_dhcp_and_rollback_undoes(db, seeded):
    admin = FakeAdmin()
    take_backup(db, admin)
    result = cutover(db, admin, CFG, dhcp_kind="pihole")
    assert admin.hosts == ["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"]
    assert admin.patches[0] == {"webserver": {"api": {"app_sudo": True}}}
    assert admin.patches[1]["dhcp"] | {} == {"active": True, "start": "192.168.1.240", "end": "192.168.1.254",
                                           "router": "192.168.1.1", "netmask": "255.255.255.0", "leaseTime": "24h",
                                           "ipv6": False}
    assert result["sync_mode"] == load_sync_mode(db) == "apply"
    rollback(db, admin)
    assert admin.patches[-2:] == [{"dhcp": {"active": False}}, {"webserver": {"api": {"app_sudo": False}}}]
    assert load_sync_mode(db) == "dry-run"
    modes = [e.payload["to"] for e in db.query(Event).filter(Event.type == "sync.mode").order_by(Event.id)]
    assert modes == ["apply", "dry-run"]


def test_cutover_refuses_when_preflight_is_red(db, seeded):
    admin = FakeAdmin(lines=())
    with pytest.raises(RuntimeError, match="preflight is not green"):
        cutover(db, admin, CFG, dhcp_kind="pihole")
    assert admin.patches == [] and load_sync_mode(db) == "dry-run"


def test_cutover_refused_when_pihole_is_dns_only(db, seeded):
    admin = FakeAdmin()
    take_backup(db, admin)
    report = preflight(db, admin, CFG, dhcp_kind="unifi", admin=admin)
    assert _checks(report)["pihole_is_dhcp_provider"] is False and not report.ready
    assert _checks(preflight(db, admin, CFG, dhcp_kind="pihole", admin=admin))["pihole_is_dhcp_provider"] is True
    for other in ("unifi", None):
        with pytest.raises(RuntimeError, match="preflight is not green"):
            cutover(db, admin, CFG, dhcp_kind=other)
    assert admin.patches == [] and admin.hosts == [] and load_sync_mode(db) == "dry-run"


def test_preflight_and_cutover_use_the_configured_lease(db, seeded):
    admin = FakeAdmin()
    take_backup(db, admin)
    cfg = PiholeConfig(url=BASE, password="pw", lease="12h")
    details = {c.name: c.detail for c in preflight(db, admin, cfg, dhcp_kind="pihole").checks}
    assert f"answers at {BASE}" in details["pihole_reachable"]
    result = cutover(db, admin, cfg, dhcp_kind="pihole")
    assert admin.hosts == ["00:00:5e:00:53:10,192.168.1.10,laptop-a,12h"]
    assert result["dhcp"]["leaseTime"] == "12h"


@respx.mock(base_url=BASE)
def test_admin_client_http_calls(respx_mock):
    respx_mock.post("/api/auth").respond(json={"session": {"valid": True, "sid": "s1", "validity": 1800}})
    respx_mock.delete("/api/auth").respond(204)
    respx_mock.get("/api/config/dhcp").respond(json={"config": {"dhcp": {"active": False}}})
    patch = respx_mock.patch("/api/config").respond(json={"config": {}})
    respx_mock.get("/api/teleporter").respond(content=b"PK\x03\x04")
    with PiholeAdmin(BASE, "secret") as admin:
        assert admin.get_config("dhcp") == {"dhcp": {"active": False}}
        admin.patch_config({"dhcp": {"active": True}})
        assert admin.teleporter() == b"PK\x03\x04"
    assert json.loads(patch.calls[0].request.content) == {"config": {"dhcp": {"active": True}}}


GUEST_LINE = "dhcp-range=tag:guest,192.168.1.200,192.168.1.229,24h"


@pytest.fixture
def pool(monkeypatch):
    for name, value in {"subnet": "192.168.1.0/24", "gateway": "192.168.1.1", "quarantine_start": "192.168.1.240",
                        "quarantine_end": "192.168.1.254", "guest_start": "192.168.1.200",
                        "guest_end": "192.168.1.229"}.items():
        monkeypatch.setattr(settings, name, value)


def _guest_check(report):
    [check] = [c for c in report.checks if c.name == "guest_rules"]
    return check


def test_guest_rules_ok_without_a_pool(db, seeded, monkeypatch):
    monkeypatch.setattr(settings, "guest_start", "")
    monkeypatch.setattr(settings, "guest_end", "")
    assert _guest_check(preflight(db, FakeAdmin(), CFG, dhcp_kind="pihole", now=NOW)).ok is True


def test_guest_rules_with_a_pool(db, seeded, pool):
    present = _guest_check(preflight(db, FakeAdmin(lines=(*QUARANTINE_LINES, GUEST_LINE)), CFG, dhcp_kind="pihole"))
    assert present.ok is True
    stale = (*QUARANTINE_LINES, "dhcp-range=tag:guest,192.168.1.100,192.168.1.110,24h")
    take_backup(db, FakeAdmin())
    for lines in (QUARANTINE_LINES, stale):
        admin = FakeAdmin(lines=lines)
        report = preflight(db, admin, CFG, dhcp_kind="pihole", admin=admin)
        # Not blocking: the cutover itself writes the guest range once it has write access.
        check = _guest_check(report)
        assert (check.ok, check.blocking, report.ready) == (None, False, True)
        assert GUEST_LINE in check.detail


def test_cutover_writes_the_guest_range(db, seeded, pool):
    admin = FakeAdmin()
    take_backup(db, admin)
    cutover(db, admin, CFG, dhcp_kind="pihole")
    assert admin.config["misc"]["dnsmasq_lines"] == ["address=/local/192.168.1.220", *QUARANTINE_LINES, GUEST_LINE]
    assert _guest_check(preflight(db, admin, CFG, dhcp_kind="pihole")).ok is True


def test_rollback_removes_only_the_guest_range_before_dropping_app_sudo(db, seeded, pool):
    admin = FakeAdmin()
    take_backup(db, admin)
    cutover(db, admin, CFG, dhcp_kind="pihole")
    assert GUEST_LINE in admin.config["misc"]["dnsmasq_lines"]
    rollback(db, admin)
    assert admin.config["misc"]["dnsmasq_lines"] == ["address=/local/192.168.1.220", *QUARANTINE_LINES]
    assert admin.patches[-3:] == [{"misc": {"dnsmasq_lines": ["address=/local/192.168.1.220", *QUARANTINE_LINES]}},
                                  {"dhcp": {"active": False}}, {"webserver": {"api": {"app_sudo": False}}}]
