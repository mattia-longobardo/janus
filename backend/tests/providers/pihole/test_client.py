import json

import httpx
import pytest
import respx

from app.providers.pihole.client import PiholeClient, PiholeError

BASE = "http://pihole.test"
LOGIN_OK = {"session": {"valid": True, "sid": "sid-1", "validity": 1800}}


def _client() -> PiholeClient:
    return PiholeClient(BASE, "secret")


@respx.mock(base_url=BASE)
def test_login_and_list_hosts(respx_mock):
    login = respx_mock.post("/api/auth").respond(json=LOGIN_OK)
    hosts = respx_mock.get("/api/config/dhcp/hosts").respond(
        json={"config": {"dhcp": {"hosts": ["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"]}}}
    )
    respx_mock.delete("/api/auth").respond(204)
    with _client() as client:
        assert client.list_hosts() == ["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"]
    assert json.loads(login.calls.last.request.content) == {"password": "secret"}
    assert hosts.calls.last.request.headers["X-FTL-SID"] == "sid-1"


@respx.mock(base_url=BASE)
def test_add_and_remove_host_url_encode_the_line(respx_mock):
    respx_mock.post("/api/auth").respond(json=LOGIN_OK)
    line = "00:00:5e:00:53:20,set:lanonly,192.168.1.120,plug-kitchen,24h"
    encoded = "00%3A00%3A5e%3A00%3A53%3A20%2Cset%3Alanonly%2C192.168.1.120%2Cplug-kitchen%2C24h"
    put = respx_mock.put(path__startswith="/api/config/dhcp/hosts/").respond(201)
    delete = respx_mock.delete(path__startswith="/api/config/dhcp/hosts/").respond(204)
    client = _client()
    client.add_host(line)
    client.remove_host(line)
    assert put.calls.last.request.url.raw_path.decode().endswith(encoded)
    assert delete.calls.last.request.url.raw_path.decode().endswith(encoded)


@respx.mock(base_url=BASE)
def test_reauth_on_401(respx_mock):
    respx_mock.post("/api/auth").mock(side_effect=[
        httpx.Response(200, json=LOGIN_OK),
        httpx.Response(200, json={"session": {"valid": True, "sid": "sid-2", "validity": 1800}}),
    ])
    route = respx_mock.get("/api/dhcp/leases").mock(side_effect=[
        httpx.Response(401, json={"error": {"key": "unauthorized"}}),
        httpx.Response(200, json={"leases": [{"ip": "192.168.1.243", "hwaddr": "00:00:5e:00:53:99"}]}),
    ])
    assert _client().list_leases() == [{"ip": "192.168.1.243", "hwaddr": "00:00:5e:00:53:99"}]
    assert route.calls.last.request.headers["X-FTL-SID"] == "sid-2"


@respx.mock(base_url=BASE)
def test_wrong_password_raises(respx_mock):
    respx_mock.post("/api/auth").respond(401, json={"session": {"valid": False}})
    with pytest.raises(PiholeError, match="login failed"):
        _client().list_hosts()


@respx.mock(base_url=BASE)
def test_unreachable_raises_pihole_error(respx_mock):
    respx_mock.post("/api/auth").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(PiholeError, match="unreachable"):
        _client().list_hosts()


@respx.mock(base_url=BASE)
def test_server_error_raises_with_status(respx_mock):
    respx_mock.post("/api/auth").respond(json=LOGIN_OK)
    respx_mock.delete("/api/dhcp/leases/192.168.1.243").respond(500, text="boom")
    with pytest.raises(PiholeError, match="HTTP 500"):
        _client().revoke_lease("192.168.1.243")


@respx.mock(base_url=BASE)
def test_close_logs_out(respx_mock):
    respx_mock.post("/api/auth").respond(json=LOGIN_OK)
    respx_mock.get("/api/config/dhcp/hosts").respond(json={"config": {"dhcp": {"hosts": []}}})
    logout = respx_mock.delete("/api/auth").respond(204)
    with _client() as client:
        client.list_hosts()
    assert logout.called


@respx.mock(base_url=BASE)
def test_list_queries_filters_by_client_and_time(respx_mock):
    respx_mock.post("/api/auth").respond(json=LOGIN_OK)
    route = respx_mock.get("/api/queries").respond(json={"queries": [{"domain": "example.org"}], "recordsFiltered": 7})
    assert _client().list_queries("192.168.1.40", 100, 200, length=50, disk=True) == ([{"domain": "example.org"}], 7)
    params = dict(route.calls.last.request.url.params)
    assert params == {"client_ip": "192.168.1.40", "from": "100", "until": "200", "length": "50", "disk": "true"}


@respx.mock(base_url=BASE, assert_all_called=False)
def test_shared_session_logs_in_once_for_concurrent_clients(respx_mock):
    from concurrent.futures import ThreadPoolExecutor

    from app.providers.pihole.client import SharedSession

    login = respx_mock.post("/api/auth").respond(json=LOGIN_OK)
    logout = respx_mock.route(method="DELETE", path="/api/auth").respond(204)
    respx_mock.get("/api/dhcp/leases").respond(json={"leases": []})
    shared = SharedSession()

    def call(_: int) -> list:
        with PiholeClient(BASE, "secret", shared=shared) as client:
            return client.list_leases()

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert list(pool.map(call, range(12))) == [[]] * 12
    assert login.call_count == 1
    assert logout.call_count == 0
    assert shared.sid == "sid-1"


@respx.mock(base_url=BASE)
def test_shared_session_renews_once_when_expired(respx_mock):
    from app.providers.pihole.client import SharedSession

    shared = SharedSession()
    shared.sid = "old"
    login = respx_mock.post("/api/auth").respond(json={"session": {"valid": True, "sid": "new", "validity": 1800}})
    leases = respx_mock.get("/api/dhcp/leases")
    leases.side_effect = lambda request: httpx.Response(
        200 if request.headers["X-FTL-SID"] == "new" else 401, json={"leases": []})
    with PiholeClient(BASE, "secret", shared=shared) as client:
        assert client.list_leases() == []
    with PiholeClient(BASE, "secret", shared=shared) as client:
        assert client.list_leases() == []
    assert login.call_count == 1
    assert shared.sid == "new"


@respx.mock(base_url=BASE)
def test_non_json_or_unexpected_replies_raise_pihole_error(respx_mock):
    respx_mock.post("/api/auth").respond(json=LOGIN_OK)
    respx_mock.delete("/api/auth").respond(204)
    respx_mock.get("/api/config/dhcp/hosts").respond(200, text="<html>maintenance</html>")
    respx_mock.get("/api/dhcp/leases").respond(200, json={"unexpected": True})
    with _client() as client:
        with pytest.raises(PiholeError) as html:
            client.list_hosts()
        assert html.value.status == 200 and "not valid JSON" in str(html.value)
        with pytest.raises(PiholeError) as shape:
            client.list_leases()
        assert "unexpected reply" in str(shape.value)
