from app.models import Access, Device
from app.providers.unifi import SPEC
from app.providers.unifi.provider import UnifiConfig, UnifiProvider
from tests.fakes_provider import app_override_dhcp
from tests.providers.unifi.fake import FakeUnifi

CFG = UnifiConfig(url="https://unifi.example", username="janus", password="pw", network_id="n1")


def _unifi(client, fake: FakeUnifi) -> None:
    app_override_dhcp(client, ("unifi", SPEC.policies, lambda: UnifiProvider(fake, CFG)))


def test_clients_name_their_uplink_and_link_known_devices(client, db):
    d = Device(mac="00:00:5E:00:53:10", name="LAPTOP_A", hostname="laptop-a", access=Access.authorized)
    db.add(d)
    db.flush()
    fake = FakeUnifi(
        online=[{"mac": "00:00:5e:00:53:10", "ip": "192.168.1.10", "ap_mac": "00:00:5e:00:53:a0", "essid": "Home",
                 "signal": -55, "uptime": 120},
                {"mac": "00:00:5e:00:53:11", "ip": "192.168.1.240", "sw_mac": "00:00:5e:00:53:b0", "sw_port": 4,
                 "uptime": 60}],
        devices=[{"mac": "00:00:5e:00:53:a0", "name": "Living room"}, {"mac": "00:00:5e:00:53:b0", "name": "Office"}])
    _unifi(client, fake)
    rows = {r["mac"]: r for r in client.get("/api/providers/unifi/clients").json()}
    assert rows["00:00:5E:00:53:10"]["uplink"] == "AP Living room" and rows["00:00:5E:00:53:10"]["device_id"] == str(d.id)
    assert rows["00:00:5E:00:53:11"]["uplink"] == "Switch Office port 4" and rows["00:00:5E:00:53:11"]["device_id"] is None


def test_clients_is_404_when_dhcp_is_not_unifi(client):
    app_override_dhcp(client, ("pihole", frozenset(), lambda: None))
    assert client.get("/api/providers/unifi/clients").status_code == 404


def test_clients_is_404_without_a_dhcp_provider(client):
    app_override_dhcp(client, None)
    assert client.get("/api/providers/unifi/clients").status_code == 404


def test_clients_is_502_when_unifi_is_unreachable(client):
    _unifi(client, FakeUnifi(fail=True))
    assert client.get("/api/providers/unifi/clients").status_code == 502
