from contextlib import contextmanager
from dataclasses import replace

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Event, Setting
from app.providers import config as pc
from app.providers.base import Capability, Policy, Role
from app.syncmode import load_sync_mode, set_sync_mode
from tests.fakes import FakeAdmin, fake_pihole


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "internal_token", "test-token")
    monkeypatch.setattr(settings, "dhcp_provider", "")
    monkeypatch.setattr(settings, "dns_provider", "")
    monkeypatch.setattr(settings, "pihole_url", "http://192.168.1.220:1000")
    monkeypatch.setattr(settings, "pihole_password", "pw")


def test_existing_install_defaults_to_pihole_for_both_roles(db):
    for role in Role:
        rc = pc.load_role(db, role)
        assert rc.kind == "pihole" and rc.source == "env" and rc.config.url == "http://192.168.1.220:1000"


def test_no_pihole_password_and_no_env_means_no_provider(db, monkeypatch):
    monkeypatch.setattr(settings, "pihole_password", "")
    assert pc.load_role(db, Role.DHCP) is None


def test_env_kind_reads_the_role_variables(monkeypatch):
    monkeypatch.setattr(settings, "dhcp_provider", "none")
    monkeypatch.setattr(settings, "dns_provider", "unifi")
    assert pc.env_kind(Role.DHCP) is None and pc.env_kind(Role.DNS) == "unifi"


@contextmanager
def _demo(admin=None):
    """The demo provider (DHCP only), next to a Pi-hole faked offline (DHCP off unless `admin` says otherwise)."""
    from app.providers import registry
    from tests.providers import fixture_pkg
    with registry.override({"demo": registry.discover(fixture_pkg)["demo"]}), fake_pihole(admin) as fake:
        yield fake


def test_pihole_dns_and_dhcp_share_one_config(db):
    pc.save_role(db, Role.DHCP, "pihole", {"url": "http://10.0.0.2", "password": "pw2"})
    dns = pc.load_role(db, Role.DNS)
    assert dns.shared and dns.kind == "pihole" and dns.config.url == "http://10.0.0.2" and dns.config.password == "pw2"


def test_role_ref_only_exposes_capabilities_of_that_role(db):
    from app.providers.runtime import role_ref
    dhcp, dns = role_ref(db, Role.DHCP), role_ref(db, Role.DNS)
    assert {"reservations", "quarantine", "dhcp_server"} <= set(dhcp["capabilities"])
    assert set(dns["capabilities"]) == {"dns_query_log", "dns_probe"} and dns["shared"] is True
    assert dhcp["policies"] == ["full", "guest", "lan_only"] and "policies" not in dns


def test_role_ref_reports_down_since(db):
    from app.providers.runtime import role_ref
    db.add(Setting(key="dhcp.down_since", value="2026-10-01T00:00:00+00:00"))
    db.flush()
    assert role_ref(db, Role.DHCP)["down_since"] == "2026-10-01T00:00:00+00:00"
    assert role_ref(db, Role.DNS)["down_since"] is None


def test_switching_dhcp_away_from_pihole_keeps_pihole_as_dns(db):
    with _demo():   # demo: DHCP only
        pc.save_role(db, Role.DHCP, "demo", {})
        dns = pc.load_role(db, Role.DNS)
        assert dns.kind == "pihole" and not dns.shared and dns.config.url == "http://192.168.1.220:1000"
        event = db.scalars(select(Event).where(Event.type == "settings.providers")).one()
        assert event.payload == {"role": "dhcp", "kind_before": "pihole", "kind_after": "demo",
                                 "forced_dry_run": False, "dns_detached": True}


def test_detached_dns_keeps_the_custom_pihole_config(db):
    pc.save_role(db, Role.DHCP, "pihole", {"url": "http://10.0.0.2", "password": "pw2"})
    with _demo():
        pc.save_role(db, Role.DHCP, "demo", {})
        dns = pc.load_role(db, Role.DNS)
        assert dns.kind == "pihole" and dns.config.url == "http://10.0.0.2" and dns.config.password == "pw2"


def test_same_as_requires_a_dhcp_provider_with_dns(db):
    with _demo():
        pc.save_role(db, Role.DHCP, "demo", {})
        with pytest.raises(pc.ConfigError, match="same_as"):
            pc.save_role(db, Role.DNS, None, None, same_as=Role.DHCP)


def test_same_as_follows_the_dhcp_provider(db):
    pc.save_role(db, Role.DNS, "pihole", {"url": "http://10.0.0.9"})
    assert not pc.load_role(db, Role.DNS).shared
    pc.save_role(db, Role.DNS, None, None, same_as=Role.DHCP)
    dns = pc.load_role(db, Role.DNS)
    assert dns.shared and dns.config.url == "http://192.168.1.220:1000"


def test_explicit_none_disables_a_role(db):
    pc.save_role(db, Role.DNS, None, None)
    assert pc.load_role(db, Role.DNS) is None
    assert pc.load_role(db, Role.DHCP).kind == "pihole"


def test_secret_is_encrypted_and_kept_when_omitted(db):
    pc.save_role(db, Role.DHCP, "pihole", {"url": "http://10.0.0.2", "password": "new"})
    raw = db.get(Setting, pc.KEY).value["dhcp"]["config"]["password"]
    assert raw.startswith("fernet:")
    pc.save_role(db, Role.DHCP, "pihole", {"url": "http://10.0.0.3"})
    assert pc.load_role(db, Role.DHCP).config.password == "new"
    assert pc.view_role(db, Role.DHCP)["config"]["password"] is True


def test_value_equal_to_env_drops_the_override(db):
    pc.save_role(db, Role.DHCP, "pihole", {"url": "http://10.0.0.2"})
    pc.save_role(db, Role.DHCP, "pihole", {"url": "http://192.168.1.220:1000", "password": "pw"})
    assert db.get(Setting, pc.KEY).value["dhcp"] == {"kind": "pihole", "config": {}}
    assert pc.load_role(db, Role.DHCP).source == "env"


def test_invalid_saved_config_falls_back_to_env_defaults(db):
    db.merge(Setting(key=pc.KEY, value={"dhcp": {"kind": "pihole", "config": {"url": 12}}}))
    db.flush()
    rc = pc.load_role(db, Role.DHCP)
    assert rc.kind == "pihole" and rc.source == "env" and rc.config.url == "http://192.168.1.220:1000"


def test_invalid_saved_config_without_valid_env_is_none(db):
    db.merge(Setting(key=pc.KEY, value={"dhcp": {"kind": "pihole", "config": {"url": None}}}))
    db.flush()
    from app.providers import registry
    spec = registry.get_spec("pihole")
    with registry.override({"pihole": replace(spec, env_defaults=lambda: {})}):
        assert pc.load_role(db, Role.DHCP) is None


def test_unknown_field_is_refused(db):
    with pytest.raises(pc.ConfigError, match="nope"):
        pc.save_role(db, Role.DHCP, "pihole", {"nope": 1})


def test_invalid_value_is_a_config_error_naming_the_field(db):
    with pytest.raises(pc.ConfigError, match="url"):
        pc.save_role(db, Role.DHCP, "pihole", {"url": 12})


def test_view_hides_secrets_and_their_schema_default(db):
    view = pc.view_role(db, Role.DHCP)
    assert view["kind"] == "pihole" and view["label"] == "Pi-hole" and view["source"] == "env"
    assert view["config"] == {"url": "http://192.168.1.220:1000", "password": True, "lease": "24h"}
    assert view["secret_fields"] == ["password"]
    assert "default" not in view["schema"]["properties"]["password"]


def test_switching_dhcp_provider_forces_dry_run(db, monkeypatch):
    monkeypatch.setattr(settings, "dhcp_provider", "none")   # from no provider: nothing is serving DHCP for Janus
    with _demo():
        set_sync_mode(db, "apply", "test")
        pc.save_role(db, Role.DHCP, "demo", {})
        assert load_sync_mode(db) == "dry-run"


def _active_admin():
    return FakeAdmin(config={"dhcp": {"active": True}})


def test_switching_away_from_pihole_serving_dhcp_needs_a_rollback_first_even_in_dry_run(db):
    with _demo(_active_admin()):
        assert load_sync_mode(db) == "dry-run"   # e.g. after `janus sync-mode dry-run` or the worker's forced dry-run
        with pytest.raises(pc.ProviderInUse, match="Pi-hole is still serving DHCP: run janus rollback first"):
            pc.save_role(db, Role.DHCP, "demo", {})
        with pytest.raises(pc.ProviderInUse, match="janus rollback"):
            pc.save_role(db, Role.DHCP, None, None)
        assert pc.load_role(db, Role.DHCP).kind == "pihole"
        pc.save_role(db, Role.DHCP, "pihole", {"lease": "12h"})   # same provider: allowed


def test_switching_away_from_pihole_with_dhcp_off_is_allowed_in_apply(db):
    with _demo() as admin:   # apply without cutover, or after the rollback: Pi-hole DHCP is off
        set_sync_mode(db, "apply", "test")
        pc.save_role(db, Role.DHCP, "demo", {})
        assert pc.load_role(db, Role.DHCP).kind == "demo" and load_sync_mode(db) == "dry-run"
        assert admin.patches == []


def test_switching_away_from_an_unreachable_pihole_is_refused(db):
    with _demo(FakeAdmin(fail=True)):
        with pytest.raises(pc.ProviderInUse, match=r"cannot verify that Pi-hole stopped serving DHCP \(.*boom\)"):
            pc.save_role(db, Role.DHCP, "demo", {})
        assert pc.load_role(db, Role.DHCP).kind == "pihole"


def test_switching_away_from_a_provider_without_dhcp_server_checks_nothing(db, monkeypatch):
    from app.providers import registry
    from tests.providers import fixture_pkg
    demo = registry.discover(fixture_pkg)["demo"]
    opened = []
    monkeypatch.setattr(settings, "dhcp_provider", "demo")
    with registry.override({"demo": replace(demo, open=lambda cfg: opened.append(cfg))}):
        set_sync_mode(db, "apply", "test")
        pc.save_role(db, Role.DHCP, None, None)
        assert pc.load_role(db, Role.DHCP) is None and opened == []


def test_kind_without_that_role_is_refused(db):
    with _demo(), pytest.raises(pc.ConfigError, match="dns"):
        pc.save_role(db, Role.DNS, "demo", {})   # demo declares only Role.DHCP


def test_unknown_kind_is_refused(db):
    with pytest.raises(pc.ConfigError, match="nope"):
        pc.save_role(db, Role.DHCP, "nope", {})


def test_runtime_capabilities_and_policies(db):
    from app.providers import runtime
    assert runtime.has_capability(db, Role.DHCP, Capability.QUARANTINE)
    assert not runtime.has_capability(db, Role.DNS, Capability.QUARANTINE)
    assert runtime.policies(db) == {Policy.FULL, Policy.LAN_ONLY, Policy.GUEST}
    with fake_pihole():
        pc.save_role(db, Role.DHCP, None, None)
    assert runtime.policies(db) == frozenset() and runtime.provider_factory(db, Role.DHCP) is None


def test_infrastructure_ips_are_the_provider_hosts(db):
    from app.providers import runtime
    assert runtime.infrastructure_ips(db) == {"192.168.1.220"}
    pc.save_role(db, Role.DNS, "pihole", {"url": "http://pihole.lan"})
    assert runtime.infrastructure_ips(db) == {"192.168.1.220"}   # hostnames are not IPs


def test_provider_factory_opens_the_configured_provider(db):
    from app.providers import runtime
    from app.providers.pihole.provider import PiholeProvider
    provider = runtime.provider_factory(db, Role.DHCP)()
    assert isinstance(provider, PiholeProvider) and provider.config.url == "http://192.168.1.220:1000"


def test_pihole_api_uses_the_role_config(db):
    from app.providers.pihole.api import current_config
    pc.save_role(db, Role.DHCP, "pihole", {"url": "http://10.0.0.2"})
    cfg, dhcp_kind = current_config(db)
    assert cfg.url == "http://10.0.0.2" and dhcp_kind == "pihole"
    with _demo():
        pc.save_role(db, Role.DHCP, "demo", {})
        cfg, dhcp_kind = current_config(db)
        assert cfg.url == "http://10.0.0.2" and dhcp_kind == "demo"   # Pi-hole kept as DNS: the cutover refuses


def test_dns_probe_host_follows_the_env_pihole_without_a_saved_config(db):
    from app.providers import runtime

    assert db.get(Setting, pc.KEY) is None   # nothing saved from Settings: env only, as in the sentinel container
    assert runtime.dns_probe_host(db) == "192.168.1.220"


def test_dns_probe_host_is_off_without_a_dns_provider_in_the_env(db, monkeypatch):
    from app.providers import runtime

    monkeypatch.setattr(settings, "pihole_password", "")
    assert runtime.dns_probe_host(db) is None
