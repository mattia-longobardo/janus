from app.models import Access, Device, Group
from app.providers.base import Policy
from app.providers.pihole import SPEC
from app.providers.pihole.provider import PiholeConfig, PiholeProvider
from tests.fakes import FakePihole
from tests.fakes_provider import FakeStore, app_override_dhcp

CFG = PiholeConfig(url="http://192.168.1.220:1000", password="pw", lease="24h")


def _seed(db):
    g = Group(name="People", color="#6FB7FF", icon="device", range_start="192.168.1.10",
              range_end="192.168.1.19", default_access=Access.authorized)
    db.add(g)
    db.flush()
    db.add(Device(mac="00:00:5E:00:53:10", name="LAPTOP_A", hostname="laptop-a", group=g,
                  static_ip="192.168.1.10", access=Access.authorized))
    db.flush()


def _use(client, fake):
    app_override_dhcp(client, ("pihole", SPEC.policies, lambda: PiholeProvider(fake, CFG)))


def test_plan_shows_diff_without_writing(client, db):
    _seed(db)
    fake = FakePihole(["garbage line"])
    _use(client, fake)
    body = client.get("/api/sync/plan").json()
    assert body == {"to_add": ["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"], "to_remove": [],
                    "unmanaged": ["garbage line"], "failed": []}
    assert fake.writes == []


def test_apply_writes(client, db):
    _seed(db)
    fake = FakePihole()
    _use(client, fake)
    assert client.post("/api/sync/apply").status_code == 200
    assert fake.hosts == ["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"]


def test_pihole_failure_is_502(client, db):
    _seed(db)
    _use(client, FakePihole(fail=True))
    response = client.get("/api/sync/plan")
    assert response.status_code == 502 and "unreachable" in response.json()["detail"]


def test_sync_talks_to_whichever_provider_holds_dhcp(client, db):
    _seed(db)
    store = FakeStore()
    app_override_dhcp(client, ("demo", frozenset({Policy.FULL}), lambda: store))
    assert client.post("/api/sync/apply").json()["to_add"] == ["00:00:5E:00:53:10,192.168.1.10,laptop-a,full"]
    assert store.writes == [("add", "00:00:5E:00:53:10,192.168.1.10,laptop-a,full")]


def test_sync_without_dhcp_provider_is_404(client, db):
    app_override_dhcp(client, None)
    assert client.get("/api/sync/plan").status_code == 404
    assert client.post("/api/sync/apply").status_code == 404


def test_mode_switch_to_apply_records_the_web_actor(client, db):
    from sqlalchemy import select

    from app.models import Event
    from app.syncmode import load_sync_mode, set_sync_mode

    set_sync_mode(db, "dry-run", actor="test")
    _use(client, FakePihole())
    response = client.post("/api/sync/mode", json={"mode": "apply"})
    assert response.status_code == 200 and response.json() == {"mode": "apply"}
    assert load_sync_mode(db) == "apply"
    event = db.scalars(select(Event).where(Event.type == "sync.mode")).all()[-1]
    assert event.payload == {"from": "dry-run", "to": "apply", "actor": "web"}
    assert client.post("/api/sync/mode", json={"mode": "dry-run"}).json() == {"mode": "dry-run"}
    assert load_sync_mode(db) == "dry-run"


def test_mode_switch_refuses_an_unknown_mode(client):
    assert client.post("/api/sync/mode", json={"mode": "yolo"}).status_code == 422


def test_mode_switch_to_apply_needs_a_dhcp_provider(client, db):
    from app.syncmode import load_sync_mode, set_sync_mode

    set_sync_mode(db, "dry-run", actor="test")
    app_override_dhcp(client, None)
    response = client.post("/api/sync/mode", json={"mode": "apply"})
    assert response.status_code == 409 and "no DHCP provider" in response.json()["detail"]
    assert load_sync_mode(db) == "dry-run"
    assert client.post("/api/sync/mode", json={"mode": "dry-run"}).status_code == 200
