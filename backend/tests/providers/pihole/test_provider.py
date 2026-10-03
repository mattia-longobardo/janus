import pytest

from app.config import settings
from app.enforcement.sync import apply_sync, plan_sync
from app.models import Access, Device, Event, Group, Setting
from app.net.ipplan import IpRange
from app.providers import registry
from app.providers.base import (
    Capability,
    DhcpServerState,
    DnsProbe,
    DnsQueryLog,
    HealthCheck,
    LeaseControl,
    Policy,
    Reservation,
    ReservationStore,
    Role,
)
from app.providers.pihole import SPEC, open_pihole
from app.providers.pihole.client import PiholeClient, PiholeError, shared_session
from app.providers.pihole.codec import parse
from app.providers.pihole.provider import PiholeConfig, PiholeProvider
from tests.fakes import FakeAdmin, FakePihole

CFG = PiholeConfig(url="http://192.168.1.220:1000", password="pw", lease="24h")


def _group(db):
    g = Group(name="People", color="#6FB7FF", icon="device", range_start="192.168.1.10", range_end="192.168.1.19",
              default_access=Access.authorized)
    db.add(g)
    db.flush()
    return g


def _device(db, group, name, mac, ip, access=Access.authorized):
    db.add(Device(mac=mac, name=name, hostname=name.lower().replace("_", "-"), group=group, static_ip=ip,
                  access=access))
    db.flush()


def test_spec_declares_what_the_provider_implements():
    p = PiholeProvider(FakePihole(), CFG)
    for proto in (ReservationStore, LeaseControl, DnsQueryLog, DnsProbe, HealthCheck, DhcpServerState):
        assert isinstance(p, proto)
    assert Capability.QUARANTINE in SPEC.capabilities and SPEC.policies == {Policy.FULL, Policy.LAN_ONLY, Policy.GUEST}
    assert SPEC.roles == {Role.DHCP, Role.DNS} and SPEC.provider_class is PiholeProvider
    assert SPEC.config_model is PiholeConfig and SPEC.secret_fields == {"password"}
    assert registry.get_spec("pihole") is SPEC
    assert [r.path for r in SPEC.router.routes] == ["/preflight"]


def test_env_defaults_come_from_todays_settings(monkeypatch):
    monkeypatch.setattr(settings, "pihole_url", "http://10.0.0.2")
    monkeypatch.setattr(settings, "pihole_password", "secret")
    monkeypatch.setattr(settings, "reservation_lease", "12h")
    assert SPEC.env_defaults() == {"url": "http://10.0.0.2", "password": "secret", "lease": "12h"}
    assert PiholeConfig(url="http://10.0.0.2").model_dump() == {"url": "http://10.0.0.2", "password": "", "lease": "24h"}


def test_codec_round_trip_is_byte_identical_to_before():
    from app.providers.pihole.codec import render
    lan = Reservation("00:00:5E:00:53:20", "plug", "192.168.1.120", Policy.LAN_ONLY)
    assert render(lan, "24h") == "00:00:5e:00:53:20,set:lanonly,192.168.1.120,plug,24h"
    assert parse(render(lan, "24h"), "24h").reservation == lan
    assert parse("00:00:5e:00:53:20,set:lanonly,192.168.1.120,plug,12h", "24h").canonical is False
    assert parse("00:00:5E:00:53:20,set:lanonly,192.168.1.120,plug,24h", "24h").canonical is True
    assert parse("not,a,reservation", "24h").reservation is None


def test_pihole_plan_is_unchanged_after_refactor(db):
    # Expected values are the as_dict() of app.pihole.sync.plan_sync (pre-refactor code) on the same scenario.
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    fake = FakePihole(hosts=["00:00:5e:00:53:99,192.168.1.99,nas,24h", "00:00:5E:00:53:10,192.168.1.10,laptop-a,12h"])
    diff = plan_sync(db, PiholeProvider(fake, CFG), "pihole", SPEC.policies)
    store = PiholeProvider(fake, CFG)
    # First run, nothing recorded yet: the nas line is in Janus' exact format, so it is recognised as Janus' own.
    assert diff.as_dict(store.describe) == {
        "to_add": ["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"],
        "to_remove": ["00:00:5E:00:53:10,192.168.1.10,laptop-a,12h", "00:00:5e:00:53:99,192.168.1.99,nas,24h"],
        "unmanaged": [],
        "failed": [],
    }


def test_pihole_plan_is_unchanged_after_refactor_with_written_macs(db):
    # Same check on an upgraded install (written MACs migrated by 0008); only the duplicate message lost
    # its " in Pi-hole" suffix (ruling R20).
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    _device(db, g, "PHONE_A", "00:00:5E:00:53:11", "192.168.1.99")
    _device(db, g, "PLUG", "00:00:5E:00:53:20", "192.168.1.12", Access.lan_only)
    _device(db, g, "BANNED", "00:00:5E:00:53:22", "192.168.1.13", Access.blocked)
    db.add(Setting(key="provider.pihole.written_macs", value=["00:00:5E:00:53:10", "00:00:5E:00:53:44"]))
    db.flush()
    fake = FakePihole(hosts=["00:00:5e:00:53:99,192.168.1.99,nas,24h", "00:00:5E:00:53:10,192.168.1.10,laptop-a,12h",
                             "00:00:5E:00:53:20,set:lanonly,192.168.1.12,plug,24h",
                             "00:00:5e:00:53:22,192.168.1.13,banned,24h",
                             "00:00:5e:00:53:44,192.168.1.14,old-phone,24h", "not a reservation"])
    store = PiholeProvider(fake, CFG)
    assert plan_sync(db, store, "pihole", SPEC.policies).as_dict(store.describe) == {
        "to_add": ["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"],
        "to_remove": ["00:00:5E:00:53:10,192.168.1.10,laptop-a,12h", "00:00:5e:00:53:22,192.168.1.13,banned,24h",
                      "00:00:5e:00:53:44,192.168.1.14,old-phone,24h"],
        "unmanaged": ["00:00:5e:00:53:99,192.168.1.99,nas,24h", "not a reservation"],
        "failed": ["00:00:5e:00:53:11,192.168.1.99,phone-a,24h: would duplicate 00:00:5e:00:53:99,192.168.1.99,nas,24h,"
                   " skipped"],
    }


def test_apply_writes_the_same_lines_as_before(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.13")
    fake = FakePihole(["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"])
    apply_sync(db, PiholeProvider(fake, CFG), "pihole", SPEC.policies)
    assert fake.writes == [
        ("remove", "00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"),
        ("add", "00:00:5e:00:53:10,192.168.1.13,laptop-a,24h"),
    ]
    assert db.get(Setting, "provider.pihole.written_macs").value == ["00:00:5E:00:53:10"]


def test_rejected_line_is_a_provider_error():
    fake = FakePihole(reject={"00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"})
    with pytest.raises(PiholeError) as exc:
        PiholeProvider(fake, CFG).add_reservation(Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10"))
    assert exc.value.rejected


def test_force_renew_revokes_the_lease_by_ip():
    fake = FakePihole()
    PiholeProvider(fake, CFG).force_renew("00:00:5E:00:53:10", "192.168.1.241")
    PiholeProvider(fake, CFG).force_renew("00:00:5E:00:53:11", None)
    assert fake.writes == [("revoke", "192.168.1.241")]


def test_query_log_is_normalized():
    fake = FakePihole()
    fake.queries = [{"time": 100.0, "domain": "ads.example", "type": "A", "status": "GRAVITY",
                     "reply": {"type": "IP"}, "client": {"ip": "192.168.1.10"}}]
    [q], total = PiholeProvider(fake, CFG).query_log("192.168.1.10", 0, 200)
    assert (q.domain, q.blocked, q.reply, total) == ("ads.example", True, "IP", 1)
    assert fake.last_query == {"client_ip": "192.168.1.10", "since": 0, "until": 200, "length": 5000, "disk": False}
    PiholeProvider(fake, CFG).query_log("192.168.1.10", 0, 25 * 3600, limit=10)
    assert fake.last_query["disk"] is True and fake.last_query["length"] == 10


def test_probe_host_and_health_check():
    fake = FakePihole(hosts=["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h", "garbage"])
    p = PiholeProvider(fake, CFG)
    assert p.probe_host() == "192.168.1.220"
    assert p.check() == "2 reservations"
    with pytest.raises(PiholeError):
        PiholeProvider(FakePihole(fail=True), CFG).check()


def test_context_manager_delegates_to_the_client():
    with pytest.raises(PiholeError):
        with PiholeProvider(FakePihole(fail=True), CFG):
            pass
    with PiholeProvider(FakePihole(), CFG) as p:
        assert isinstance(p, PiholeProvider)


def test_open_pihole_shares_one_login_per_url():
    provider = open_pihole(PiholeConfig(url="http://192.168.1.220:1000", password="pw"))
    client = provider.client
    assert isinstance(client, PiholeClient) and client._shared is shared_session("http://192.168.1.220:1000")
    client.close()


POOL = IpRange.parse("192.168.1.200", "192.168.1.229")
OTHERS = ["dhcp-option=tag:!known,option:router", "address=/x.lan/10.0.0.9"]


@pytest.fixture
def pool(monkeypatch):
    for name, value in {"subnet": "192.168.1.0/24", "gateway": "192.168.1.1", "quarantine_start": "192.168.1.240",
                        "quarantine_end": "192.168.1.254", "guest_start": "192.168.1.200",
                        "guest_end": "192.168.1.229"}.items():
        monkeypatch.setattr(settings, name, value)


def test_guest_range_lines_are_managed_without_touching_others():
    admin = FakeAdmin(config={"misc": {"dnsmasq_lines": list(OTHERS)}})
    p = PiholeProvider(admin, CFG)
    p.ensure_guest_range(POOL, "24h")
    lines = admin.config["misc"]["dnsmasq_lines"]
    assert lines == [*OTHERS, "dhcp-range=tag:guest,192.168.1.200,192.168.1.229,24h"]
    p.ensure_guest_range(None, "24h")
    assert admin.config["misc"]["dnsmasq_lines"] == OTHERS


def test_guest_range_is_replaced_and_unchanged_lines_are_not_patched():
    admin = FakeAdmin(config={"misc": {"dnsmasq_lines": [OTHERS[0], "dhcp-range=tag:guest,192.168.1.100,192.168.1.110,12h",
                                                         OTHERS[1]]}})
    p = PiholeProvider(admin, CFG)
    p.ensure_guest_range(POOL, "24h")
    assert admin.config["misc"]["dnsmasq_lines"] == [*OTHERS, "dhcp-range=tag:guest,192.168.1.200,192.168.1.229,24h"]
    patches = len(admin.patches)
    p.ensure_guest_range(POOL, "24h")
    p.ensure_guest_range(None, "24h")
    p.ensure_guest_range(None, "24h")
    assert len(admin.patches) == patches + 1


def test_guest_reservation_round_trip_through_apply(db, pool):
    db.add(Device(mac="00:00:5E:00:53:60", name="Anna", hostname="anna-phone", access=Access.guest))
    db.flush()
    fake = FakePihole()
    apply_sync(db, PiholeProvider(fake, CFG), "pihole", SPEC.policies)
    assert fake.hosts == ["00:00:5e:00:53:60,set:guest,anna-phone,24h"]
    assert fake.config["misc"]["dnsmasq_lines"][-1] == "dhcp-range=tag:guest,192.168.1.200,192.168.1.229,24h"
    store = PiholeProvider(fake, CFG)
    assert plan_sync(db, store, "pihole", SPEC.policies).empty


def test_after_sync_uses_the_configured_lease(db, pool):
    fake = FakePihole()
    PiholeProvider(fake, PiholeConfig(url=CFG.url, password="pw", lease="12h")).after_sync(db)
    assert fake.config["misc"]["dnsmasq_lines"][-1] == "dhcp-range=tag:guest,192.168.1.200,192.168.1.229,12h"


def test_plan_never_touches_the_guest_range(db, pool):
    fake = FakePihole()
    plan_sync(db, PiholeProvider(fake, CFG), "pihole", SPEC.policies)
    assert fake.patches == []


def test_guest_range_without_app_sudo_is_a_sync_failure_not_a_crash(db, pool):
    fake = FakePihole()
    fake.patch_status = 403
    apply_sync(db, PiholeProvider(fake, CFG), "pihole", SPEC.policies)
    failed = [e.payload for e in db.query(Event).filter(Event.type == "sync.failed")]
    assert failed == [{"failed": ["guest range needs app_sudo (run the cutover)"]}]


def test_guest_range_unreachable_pihole_still_raises(db, pool):
    fake = FakePihole()
    fake.fail_config = True
    with pytest.raises(PiholeError):
        PiholeProvider(fake, CFG).after_sync(db)


def _failures(db):
    return [e.payload for e in db.query(Event).filter(Event.type == "sync.failed").order_by(Event.id)]


def test_guest_range_failure_is_reported_once_until_it_changes(db, pool):
    fake = FakePihole()
    fake.patch_status = 403
    store = PiholeProvider(fake, CFG)
    apply_sync(db, store, "pihole", SPEC.policies)
    apply_sync(db, store, "pihole", SPEC.policies)
    assert _failures(db) == [{"failed": ["guest range needs app_sudo (run the cutover)"]}]
    assert db.get(Setting, "provider.pihole.guest_range_error") is not None
    fake.patch_status = None
    apply_sync(db, store, "pihole", SPEC.policies)
    assert db.get(Setting, "provider.pihole.guest_range_error") is None
    assert len(_failures(db)) == 1
    fake.config["misc"]["dnsmasq_lines"] = []   # someone removed the line, and app_sudo is off again
    fake.patch_status = 403
    apply_sync(db, store, "pihole", SPEC.policies)
    apply_sync(db, store, "pihole", SPEC.policies)
    assert len(_failures(db)) == 2


@pytest.mark.parametrize("reply", [{}, {"misc": {}}, {"misc": {"dnsmasq_lines": "x"}}, {"misc": None}])
def test_unexpected_dnsmasq_lines_reply_is_a_provider_error(reply):
    fake = FakePihole()
    fake.config = reply
    fake.get_config = lambda path: reply
    with pytest.raises(PiholeError):
        PiholeProvider(fake, CFG).ensure_guest_range(POOL, "24h")


@pytest.mark.parametrize("active", [True, False])
def test_dhcp_server_active_reads_pihole_dhcp_active(active):
    assert PiholeProvider(FakeAdmin(config={"dhcp": {"active": active}}), CFG).dhcp_server_active() is active


@pytest.mark.parametrize("reply", [{}, {"dhcp": {}}, {"dhcp": None}, {"dhcp": {"active": "yes"}}])
def test_unexpected_dhcp_reply_is_a_provider_error(reply):
    fake = FakeAdmin()
    fake.get_config = lambda path: reply
    with pytest.raises(PiholeError, match="unexpected reply"):
        PiholeProvider(fake, CFG).dhcp_server_active()


def test_dhcp_server_active_on_unreachable_pihole_raises():
    with pytest.raises(PiholeError):
        PiholeProvider(FakeAdmin(fail=True), CFG).dhcp_server_active()


def test_padded_guest_line_counts_as_present():
    admin = FakeAdmin(config={"misc": {"dnsmasq_lines": [OTHERS[0], " dhcp-range=tag:guest,192.168.1.200,192.168.1.229,24h "]}})
    PiholeProvider(admin, CFG).ensure_guest_range(POOL, "24h")
    assert admin.patches == []


@pytest.mark.parametrize("lease", ["24h,x", "24h\ndhcp-range=1", "", "h", "1 h"])
def test_lease_cannot_inject_into_dnsmasq_lines(lease):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PiholeConfig(url=CFG.url, lease=lease)


@pytest.mark.parametrize("lease", ["24h", "3600", "45m", "2d", "1w", "infinite"])
def test_valid_leases(lease):
    assert PiholeConfig(url=CFG.url, lease=lease).lease == lease


def test_api_refuses_a_lease_with_a_comma(client):
    r = client.put("/api/providers/dhcp", json={"kind": "pihole", "config": {"url": "http://10.0.0.2", "lease": "1h,x"}})
    assert r.status_code == 422
