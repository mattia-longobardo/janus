import pytest

from app.config import settings
from app.enforcement.sync import apply_sync, plan_sync
from app.models import Access, Device, Group
from app.providers import registry
from app.providers.base import (
    Capability,
    HealthCheck,
    LeaseControl,
    Policy,
    Reservation,
    ReservationStore,
    Role,
)
from app.providers.unifi import SPEC, open_unifi
from app.providers.unifi.client import UnifiClient, UnifiError
from app.providers.unifi.provider import GUEST_NOTE, UnifiConfig, UnifiProvider
from tests.providers.unifi.fake import FakeUnifi

CFG = UnifiConfig(url="https://unifi.example", username="janus", password="pw", network_id="n1")
MAC = "00:00:5E:00:53:10"
mac = MAC.lower()


def test_full_reservation_sets_fixed_ip_on_the_lan_network():
    fake = FakeUnifi()
    UnifiProvider(fake, CFG).add_reservation(Reservation(MAC, "laptop-a", "192.168.1.10"))
    assert fake.users[mac].items() >= {"use_fixedip": True, "fixed_ip": "192.168.1.10", "network_id": "n1",
                                       "name": "laptop-a", "note": "janus:full"}.items()


def test_full_reservation_reads_back_canonical():
    fake = FakeUnifi()
    p = UnifiProvider(fake, CFG)
    r = Reservation(MAC, "laptop-a", "192.168.1.10")
    p.add_reservation(r)
    [entry] = p.list_reservations()
    assert entry.reservation == r and entry.canonical
    assert entry.mac == MAC and entry.ip == "192.168.1.10"
    assert entry.key == fake.users[mac]["_id"] and entry.display == f"laptop-a ({MAC})"


def test_full_on_another_network_is_not_canonical():
    fake = FakeUnifi(users=[{"_id": "u1", "mac": mac, "name": "laptop-a", "use_fixedip": True,
                             "fixed_ip": "192.168.1.10", "network_id": "other", "note": "janus:full"}])
    [entry] = UnifiProvider(fake, CFG).list_reservations()
    assert entry.reservation == Reservation(MAC, "laptop-a", "192.168.1.10") and not entry.canonical


def test_full_removal_clears_the_fixed_ip_and_never_forgets():
    fake = FakeUnifi()
    p = UnifiProvider(fake, CFG)
    p.add_reservation(Reservation(MAC, "laptop-a", "192.168.1.10"))
    [entry] = p.list_reservations()
    p.remove_reservation(entry)
    assert fake.users[mac].items() >= {"use_fixedip": False, "fixed_ip": "", "note": ""}.items()
    assert p.list_reservations() == []


def test_hand_made_fixed_ip_and_block_are_unmanaged():
    """Without Janus' note they are not Janus' reservations, but the duplicate guard still sees MAC and IP."""
    fake = FakeUnifi(users=[
        {"_id": "u1", "mac": mac, "name": "nas", "use_fixedip": True, "fixed_ip": "192.168.1.10", "network_id": "n1"},
        {"_id": "u2", "mac": "00:00:5e:00:53:11", "name": "kid", "blocked": True, "note": "grounded"},
    ])
    entries = UnifiProvider(fake, CFG).list_reservations()
    assert [(e.mac, e.ip, e.reservation) for e in entries] == [(MAC, "192.168.1.10", None),
                                                                ("00:00:5E:00:53:11", None, None)]


def test_full_removal_keeps_the_client_name():
    fake = FakeUnifi()
    p = UnifiProvider(fake, CFG)
    p.add_reservation(Reservation(MAC, "laptop-a", "192.168.1.10"))
    fake.users[mac]["name"] = "Renamed in UniFi"
    [entry] = p.list_reservations()
    p.remove_reservation(entry)
    assert fake.updates[-1] == (entry.key, {"note": "", "noted": False, "use_fixedip": False, "fixed_ip": ""})
    assert fake.users[mac]["name"] == "Renamed in UniFi"


def test_guest_clears_fixed_ip_and_writes_the_janus_note():
    fake = FakeUnifi(users=[{"_id": "u1", "mac": mac, "name": "laptop-a", "use_fixedip": True,
                             "fixed_ip": "192.168.1.10", "network_id": "n1"}])
    p = UnifiProvider(fake, CFG)
    p.add_reservation(Reservation(MAC, "laptop-a", None, Policy.GUEST))
    assert fake.users[mac].items() >= {"use_fixedip": False, "fixed_ip": "", "note": GUEST_NOTE}.items()
    [entry] = p.list_reservations()
    assert entry.reservation == Reservation(MAC, "laptop-a", None, Policy.GUEST) and entry.canonical
    assert entry.ip is None


def test_guest_removal_clears_the_note():
    fake = FakeUnifi()
    p = UnifiProvider(fake, CFG)
    p.add_reservation(Reservation(MAC, "laptop-a", None, Policy.GUEST))
    [entry] = p.list_reservations()
    p.remove_reservation(entry)
    assert fake.users[mac]["note"] == "" and p.list_reservations() == []


def test_full_over_a_guest_drops_the_guest_note():
    fake = FakeUnifi()
    p = UnifiProvider(fake, CFG)
    p.add_reservation(Reservation(MAC, "laptop-a", None, Policy.GUEST))
    [entry] = p.list_reservations()
    p.remove_reservation(entry)
    p.add_reservation(Reservation(MAC, "laptop-a", "192.168.1.10"))
    [entry] = p.list_reservations()
    assert entry.reservation.policy is Policy.FULL and entry.canonical


def test_fixed_ip_with_a_stale_guest_note_is_rewritten():
    fake = FakeUnifi(users=[{"_id": "u1", "mac": mac, "name": "laptop-a", "use_fixedip": True,
                             "fixed_ip": "192.168.1.10", "network_id": "n1", "note": GUEST_NOTE}])
    [entry] = UnifiProvider(fake, CFG).list_reservations()
    assert entry.reservation.policy is Policy.FULL and not entry.canonical


def test_blocked_uses_block_sta_and_removal_unblocks():
    fake = FakeUnifi()
    p = UnifiProvider(fake, CFG)
    p.add_reservation(Reservation("00:00:5E:00:53:30", "bad", None, Policy.BLOCKED))
    [entry] = p.list_reservations()
    p.remove_reservation(entry)
    assert fake.commands == [("block-sta", "00:00:5e:00:53:30"), ("unblock-sta", "00:00:5e:00:53:30")]


def test_blocked_reads_back_with_its_name_and_keeps_its_fixed_ip_visible():
    fake = FakeUnifi(users=[{"_id": "u1", "mac": mac, "name": "bad", "blocked": True, "use_fixedip": True,
                             "fixed_ip": "192.168.1.10", "network_id": "n1", "note": "janus:blocked"}])
    [entry] = UnifiProvider(fake, CFG).list_reservations()
    assert entry.reservation == Reservation(MAC, "bad", None, Policy.BLOCKED) and entry.canonical
    assert entry.ip == "192.168.1.10"   # the duplicate-IP guard still sees the address


def test_blocking_a_known_client_names_it_after_the_device():
    fake = FakeUnifi(users=[{"_id": "u1", "mac": mac, "name": "Old name"}])
    p = UnifiProvider(fake, CFG)
    p.add_reservation(Reservation(MAC, "bad", None, Policy.BLOCKED))
    [entry] = p.list_reservations()
    assert entry.reservation == Reservation(MAC, "bad", None, Policy.BLOCKED) and entry.canonical
    assert fake.users[mac]["note"] == "janus:blocked"


def test_unrelated_known_clients_are_not_reservations():
    fake = FakeUnifi(users=[{"_id": "x", "mac": "00:00:5e:00:53:99", "name": "tv"}])
    assert UnifiProvider(fake, CFG).list_reservations() == []


def test_force_renew_kicks_the_station():
    fake = FakeUnifi()
    UnifiProvider(fake, CFG).force_renew(MAC, "192.168.1.10")
    assert fake.commands == [("kick-sta", mac)]


def test_force_renew_on_offline_device_is_quiet():
    fake = FakeUnifi(offline={"00:00:5e:00:53:10"})
    UnifiProvider(fake, CFG).force_renew("00:00:5E:00:53:10", None)


def test_force_renew_without_mac_does_nothing():
    fake = FakeUnifi()
    UnifiProvider(fake, CFG).force_renew("", "192.168.1.10")
    assert fake.commands == []


def test_force_renew_reports_other_errors():
    fake = FakeUnifi(fail=True)
    with pytest.raises(UnifiError):
        UnifiProvider(fake, CFG).force_renew(MAC, None)


def test_spec_does_not_claim_lan_only():
    assert Policy.LAN_ONLY not in SPEC.policies


def test_spec_is_discovered_as_a_dhcp_only_provider():
    spec = registry.get_spec("unifi")
    assert spec is SPEC and spec.roles == {Role.DHCP} and spec.secret_fields == {"password"}
    assert spec.capabilities == {Capability.RESERVATIONS, Capability.FORCE_RENEW, Capability.CLIENT_INVENTORY}
    assert spec.policies == {Policy.FULL, Policy.GUEST, Policy.BLOCKED}
    p = UnifiProvider(FakeUnifi(), CFG)
    assert isinstance(p, ReservationStore) and isinstance(p, LeaseControl) and isinstance(p, HealthCheck)


def test_env_defaults_come_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "unifi_url", "https://192.168.1.2")
    monkeypatch.setattr(settings, "unifi_username", "janus")
    monkeypatch.setattr(settings, "unifi_password", "secret")
    cfg = SPEC.config_model(**SPEC.env_defaults())
    assert (cfg.url, cfg.username, cfg.password, cfg.site, cfg.network_id) == (
        "https://192.168.1.2", "janus", "secret", "default", "")


def test_empty_network_id_resolves_from_janus_gateway():
    fake = FakeUnifi(networks=[{"_id": "wan", "purpose": "wan"},
                               {"_id": "iot", "ip_subnet": "10.0.20.1/24"},
                               {"_id": "lan", "ip_subnet": "192.168.1.1/24"}])
    p = UnifiProvider(fake, CFG.model_copy(update={"network_id": ""}), lan=lambda: ("192.168.1.0/24", "192.168.1.1"))
    p.add_reservation(Reservation(MAC, "laptop-a", "192.168.1.10"))
    assert fake.users[mac]["network_id"] == "lan"
    assert "lan" in p.check()


def test_unresolvable_network_fails_the_health_check_and_full_writes():
    fake = FakeUnifi(networks=[{"_id": "iot", "ip_subnet": "10.0.20.1/24"}])
    p = UnifiProvider(fake, CFG.model_copy(update={"network_id": ""}), lan=lambda: ("192.168.1.0/24", "192.168.1.1"))
    with pytest.raises(UnifiError, match="no UniFi network matches subnet") as exc:
        p.check()
    assert exc.value.status == 400
    with pytest.raises(UnifiError) as exc:
        p.add_reservation(Reservation(MAC, "laptop-a", "192.168.1.10"))
    assert exc.value.rejected
    p.add_reservation(Reservation(MAC, "laptop-a", None, Policy.GUEST))   # guest needs no network


def test_check_summarises_reservations():
    fake = FakeUnifi(users=[{"_id": "u1", "mac": mac, "name": "a", "blocked": True, "note": "janus:blocked"},
                            {"_id": "u2", "mac": "00:00:5e:00:53:11", "name": "tv"}])
    assert UnifiProvider(fake, CFG).check() == "1 reservations, 2 known clients, network n1"


def test_check_reads_known_clients_once():
    fake = FakeUnifi()
    calls = []
    real = fake.list_known
    fake.list_known = lambda: calls.append(1) or real()
    UnifiProvider(fake, CFG).check()
    assert calls == [1]


def test_check_reports_an_unreachable_controller():
    with pytest.raises(UnifiError):
        UnifiProvider(FakeUnifi(fail=True), CFG).check()


def test_clients_name_their_uplink():
    fake = FakeUnifi(
        users=[{"_id": "u1", "mac": mac, "name": "laptop-a"},
               {"_id": "u3", "mac": "00:00:5e:00:53:12", "name": "printer", "use_fixedip": True,
                "fixed_ip": "192.168.1.12"}],
        online=[{"mac": mac, "ip": "192.168.1.10", "ap_mac": "00:00:5e:00:53:a0", "essid": "Home", "signal": -55,
                 "uptime": 120},
                {"mac": "00:00:5e:00:53:11", "hostname": "nas", "ip": "192.168.1.240", "sw_mac": "00:00:5e:00:53:b0",
                 "sw_port": 4, "uptime": 60}],
        devices=[{"mac": "00:00:5e:00:53:a0", "name": "Living room"}, {"mac": "00:00:5e:00:53:b0", "name": "Office"}])
    rows = {r["mac"]: r for r in UnifiProvider(fake, CFG).clients()}
    assert rows[MAC] == {"mac": MAC, "name": "laptop-a", "ip": "192.168.1.10", "online": True,
                         "uplink": "AP Living room", "ssid": "Home", "signal": -55, "uptime_s": 120}
    assert rows["00:00:5E:00:53:11"]["uplink"] == "Switch Office port 4"
    assert rows["00:00:5E:00:53:11"]["name"] == "nas" and rows["00:00:5E:00:53:11"]["ssid"] is None
    assert rows["00:00:5E:00:53:12"] == {"mac": "00:00:5E:00:53:12", "name": "printer", "ip": "192.168.1.12",
                                         "online": False, "uplink": None, "ssid": None, "signal": None,
                                         "uptime_s": None}


def test_open_unifi_builds_a_client_and_resolves_the_lan_lazily(monkeypatch):
    calls = []
    monkeypatch.setattr("app.providers.unifi._janus_lan", lambda: calls.append(1) or ("192.168.1.0/24", "192.168.1.1"))
    cfg = CFG.model_copy(update={"network_id": ""})
    with open_unifi(cfg) as p:
        assert isinstance(p, UnifiProvider) and isinstance(p.client, UnifiClient)
        assert calls == []   # opening touches neither the controller nor the database


def _group(db):
    g = Group(name="People", color="#6FB7FF", icon="device", range_start="192.168.1.10", range_end="192.168.1.19",
              default_access=Access.authorized)
    db.add(g)
    db.flush()
    return g


def test_end_to_end_apply(db):
    g = _group(db)
    db.add(Device(mac=MAC, name="LAPTOP_A", hostname="laptop-a", group=g, static_ip="192.168.1.10",
                  access=Access.authorized))
    db.flush()
    fake = FakeUnifi()
    diff = apply_sync(db, UnifiProvider(fake, CFG), "unifi", SPEC.policies)
    assert len(diff.to_add) == 1 and fake.users[mac]["fixed_ip"] == "192.168.1.10"
    assert plan_sync(db, UnifiProvider(fake, CFG), "unifi", SPEC.policies).empty


def test_apply_converges_for_every_policy_and_leaves_unmanaged_alone(db):
    g = _group(db)
    db.add_all([
        Device(mac=MAC, name="A", hostname="a", group=g, static_ip="192.168.1.10", access=Access.authorized),
        Device(mac="00:00:5E:00:53:11", name="B", hostname="b", group=g, access=Access.guest),
        Device(mac="00:00:5E:00:53:12", name="C", hostname="c", group=g, access=Access.blocked),
        Device(mac="00:00:5E:00:53:13", name="D", hostname="d", group=g, static_ip="192.168.1.13",
               access=Access.lan_only),
    ])
    db.flush()
    stranger = {"_id": "s1", "mac": "00:00:5e:00:53:99", "name": "neighbour", "use_fixedip": True,
                "fixed_ip": "192.168.1.50", "network_id": "n1"}
    banned = {"_id": "s3", "mac": "00:00:5e:00:53:97", "name": "banned", "blocked": True}
    fake = FakeUnifi(users=[stranger, banned, {"_id": "s2", "mac": "00:00:5e:00:53:98", "name": "tv"}])
    diff = apply_sync(db, UnifiProvider(fake, CFG), "unifi", SPEC.policies)
    assert {r.mac for r in diff.to_add} == {MAC, "00:00:5E:00:53:11", "00:00:5E:00:53:12"}   # lan_only: unsupported
    assert sorted(e.key for e in diff.unmanaged) == ["s1", "s3"] and not diff.failed and not diff.to_remove
    again = plan_sync(db, UnifiProvider(fake, CFG), "unifi", SPEC.policies)
    assert again.empty, again
    assert fake.users["00:00:5e:00:53:99"] == stranger and fake.users["00:00:5e:00:53:97"] == banned
    assert fake.commands == [("block-sta", "00:00:5e:00:53:12")]


def test_apply_rewrites_a_drifted_entry(db):
    g = _group(db)
    db.add(Device(mac=MAC, name="A", hostname="a", group=g, static_ip="192.168.1.10", access=Access.authorized))
    db.flush()
    fake = FakeUnifi(users=[{"_id": "u1", "mac": mac, "name": "a", "use_fixedip": True, "fixed_ip": "192.168.1.10",
                             "network_id": "old", "note": "janus:full"}])
    diff = apply_sync(db, UnifiProvider(fake, CFG), "unifi", SPEC.policies)
    assert [e.key for e in diff.to_remove] == ["u1"] and len(diff.to_add) == 1
    assert fake.users[mac]["network_id"] == "n1"
    assert plan_sync(db, UnifiProvider(fake, CFG), "unifi", SPEC.policies).empty


def _pending(db, mac_, name):
    db.add(Device(mac=mac_, name=name.upper(), hostname=name, access=Access.pending))
    db.flush()


def test_apply_never_unblocks_a_hand_blocked_pending_device(db):
    _pending(db, MAC, "kid")
    fake = FakeUnifi(users=[{"_id": "u1", "mac": mac, "name": "Kid tablet", "blocked": True}])
    diff = apply_sync(db, UnifiProvider(fake, CFG), "unifi", SPEC.policies)
    assert fake.commands == [] and fake.updates == [] and fake.users[mac]["blocked"] is True
    assert [e.key for e in diff.unmanaged] == ["u1"] and not diff.to_remove


def test_apply_never_clears_a_hand_set_fixed_ip_of_a_pending_device(db):
    _pending(db, MAC, "nas")
    user = {"_id": "u1", "mac": mac, "name": "NAS", "use_fixedip": True, "fixed_ip": "192.168.1.50", "network_id": "n1"}
    fake = FakeUnifi(users=[user])
    diff = apply_sync(db, UnifiProvider(fake, CFG), "unifi", SPEC.policies)
    assert fake.updates == [] and fake.users[mac] == user
    assert [e.key for e in diff.unmanaged] == ["u1"] and not diff.to_remove


def test_authorized_device_over_a_hand_set_fixed_ip_is_reported_not_overwritten(db):
    g = _group(db)
    db.add(Device(mac=MAC, name="A", hostname="a", group=g, static_ip="192.168.1.10", access=Access.authorized))
    db.flush()
    user = {"_id": "u1", "mac": mac, "name": "NAS", "use_fixedip": True, "fixed_ip": "192.168.1.50", "network_id": "n1"}
    fake = FakeUnifi(users=[user])
    diff = apply_sync(db, UnifiProvider(fake, CFG), "unifi", SPEC.policies)
    assert fake.updates == [] and fake.users[mac] == user and not diff.to_add
    assert len(diff.failed) == 1 and "would duplicate" in diff.failed[0]


def test_noted_janus_entries_still_converge(db):
    g = _group(db)
    db.add_all([
        Device(mac=MAC, name="A", hostname="a", group=g, static_ip="192.168.1.10", access=Access.authorized),
        Device(mac="00:00:5E:00:53:11", name="B", hostname="b", group=g, access=Access.guest),
    ])
    db.flush()
    fake = FakeUnifi(users=[
        {"_id": "u1", "mac": mac, "name": "a", "use_fixedip": True, "fixed_ip": "192.168.1.11", "network_id": "n1",
         "note": "janus:full"},
        {"_id": "u2", "mac": "00:00:5e:00:53:11", "name": "b", "blocked": True, "note": "janus:blocked"},
    ])
    diff = apply_sync(db, UnifiProvider(fake, CFG), "unifi", SPEC.policies)
    assert sorted(e.key for e in diff.to_remove) == ["u1", "u2"] and len(diff.to_add) == 2 and not diff.failed
    assert fake.users[mac]["fixed_ip"] == "192.168.1.10" and fake.users["00:00:5e:00:53:11"]["blocked"] is False
    assert fake.users["00:00:5e:00:53:11"]["note"] == GUEST_NOTE
    assert plan_sync(db, UnifiProvider(fake, CFG), "unifi", SPEC.policies).empty
