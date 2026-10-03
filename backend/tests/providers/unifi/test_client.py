import json

import httpx
import pytest
import respx

from app.providers.unifi.client import UnifiClient, UnifiError

BASE = "https://unifi.example"
P = f"{BASE}/proxy/network/api/s/default"
OK = {"meta": {"rc": "ok"}, "data": []}


def _login_ok(csrf: str = "c1") -> httpx.Response:
    return httpx.Response(200, headers={"x-csrf-token": csrf, "set-cookie": "TOKEN=t; Path=/"})


@respx.mock
def test_unifi_os_login_then_csrf_on_writes():
    login = respx.post(f"{BASE}/api/auth/login").mock(return_value=_login_ok())
    users = respx.get(f"{P}/rest/user").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "u1", "mac": "00:00:5e:00:53:10"}]}))
    put = respx.put(f"{P}/rest/user/u1").mock(return_value=httpx.Response(200, json=OK))
    with UnifiClient(BASE, username="janus", password="pw") as c:
        assert c.list_known()[0]["_id"] == "u1"
        c.set_fixed_ip("u1", ip="192.168.1.10", network_id="n1", name="laptop-a")
    assert json.loads(login.calls[0].request.read()) == {"username": "janus", "password": "pw"}
    assert put.calls[0].request.headers["x-csrf-token"] == "c1"
    assert put.calls[0].request.read() == b'{"use_fixedip":true,"fixed_ip":"192.168.1.10","network_id":"n1","name":"laptop-a"}'
    assert users.called and login.call_count == 1


@respx.mock
def test_set_fixed_ip_none_clears_the_reservation():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=_login_ok())
    put = respx.put(f"{P}/rest/user/u1").mock(return_value=httpx.Response(200, json=OK))
    with UnifiClient(BASE, username="janus", password="pw") as c:
        c.set_fixed_ip("u1", ip=None, network_id=None, name="laptop-a")
    assert json.loads(put.calls[0].request.read()) == {"use_fixedip": False, "fixed_ip": "", "network_id": "", "name": "laptop-a"}


@respx.mock
def test_classic_controller_uses_api_login_and_no_prefix():
    login = respx.post(f"{BASE}/api/login").mock(return_value=httpx.Response(200, json=OK))
    nets = respx.get(f"{BASE}/api/s/lab/rest/networkconf").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "n1"}]}))
    with UnifiClient(BASE, username="janus", password="pw", site="lab", unifi_os=False) as c:
        assert c.list_networks() == [{"_id": "n1"}]
    assert login.called and nets.called


@respx.mock
def test_list_online_and_devices():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=_login_ok())
    respx.get(f"{P}/stat/sta").mock(return_value=httpx.Response(200, json={"data": [{"mac": "00:00:5e:00:53:10"}]}))
    respx.get(f"{P}/stat/device").mock(return_value=httpx.Response(200, json={"data": [{"mac": "00:00:5e:00:53:01", "name": "ap-1"}]}))
    with UnifiClient(BASE, username="janus", password="pw") as c:
        assert c.list_online() == [{"mac": "00:00:5e:00:53:10"}]
        assert c.list_devices()[0]["name"] == "ap-1"


@respx.mock
def test_ensure_known_returns_existing_without_creating():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=_login_ok())
    respx.get(f"{P}/rest/user").mock(return_value=httpx.Response(200, json={"data": [{"_id": "u1", "mac": "00:00:5e:00:53:10"}]}))
    create = respx.post(f"{P}/group/user").mock(return_value=httpx.Response(200, json=OK))
    with UnifiClient(BASE, username="janus", password="pw") as c:
        assert c.ensure_known("00:00:5E:00:53:10", "laptop-a")["_id"] == "u1"
    assert not create.called


@respx.mock
def test_ensure_known_creates_a_missing_client():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=_login_ok())
    respx.get(f"{P}/rest/user").mock(side_effect=[
        httpx.Response(200, json={"data": []}),
        httpx.Response(200, json={"data": [{"_id": "u2", "mac": "00:00:5e:00:53:11"}]}),
    ])
    create = respx.post(f"{P}/group/user").mock(return_value=httpx.Response(200, json=OK))
    with UnifiClient(BASE, username="janus", password="pw") as c:
        assert c.ensure_known("00:00:5E:00:53:11", "plug")["_id"] == "u2"
    assert json.loads(create.calls[0].request.read()) == {"objects": [{"data": {"mac": "00:00:5e:00:53:11", "name": "plug"}}]}


@respx.mock
def test_stamgr_posts_cmd_and_mac():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=_login_ok())
    cmd = respx.post(f"{P}/cmd/stamgr").mock(return_value=httpx.Response(200, json=OK))
    with UnifiClient(BASE, username="janus", password="pw") as c:
        c.stamgr("block-sta", "00:00:5E:00:53:10")
    assert json.loads(cmd.calls[0].request.read()) == {"cmd": "block-sta", "mac": "00:00:5e:00:53:10"}
    assert cmd.calls[0].request.headers["x-csrf-token"] == "c1"


@respx.mock
def test_reauth_on_401_retries_once():
    login = respx.post(f"{BASE}/api/auth/login").mock(side_effect=[_login_ok("c1"), _login_ok("c2")])
    route = respx.get(f"{P}/stat/sta").mock(side_effect=[
        httpx.Response(401), httpx.Response(200, json={"data": [{"mac": "x"}]})])
    with UnifiClient(BASE, username="janus", password="pw") as c:
        assert c.list_online() == [{"mac": "x"}]
    assert login.call_count == 2 and route.call_count == 2


@respx.mock
def test_persistent_401_is_an_error():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=_login_ok())
    respx.get(f"{P}/stat/sta").mock(return_value=httpx.Response(401))
    with UnifiClient(BASE, username="janus", password="pw") as c, pytest.raises(UnifiError) as exc:
        c.list_online()
    assert exc.value.status == 401


@respx.mock
def test_http_error_carries_status():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=_login_ok())
    respx.get(f"{P}/rest/user").mock(return_value=httpx.Response(403))
    with UnifiClient(BASE, username="janus", password="pw") as c, pytest.raises(UnifiError) as exc:
        c.list_known()
    assert exc.value.status == 403 and exc.value.rejected


@respx.mock
def test_server_error_is_not_a_rejection():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=_login_ok())
    respx.get(f"{P}/rest/user").mock(return_value=httpx.Response(502))
    with UnifiClient(BASE, username="janus", password="pw") as c, pytest.raises(UnifiError) as exc:
        c.list_known()
    assert exc.value.status == 502 and not exc.value.rejected


@respx.mock
def test_wrong_password_raises():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=httpx.Response(403))
    with UnifiClient(BASE, username="janus", password="bad") as c, pytest.raises(UnifiError, match="login failed"):
        c.list_known()


@respx.mock
def test_rc_error_is_a_rejection():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=httpx.Response(200))
    respx.post(f"{P}/cmd/stamgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "error", "msg": "api.err.UnknownStation"}}))
    with UnifiClient(BASE, username="janus", password="pw") as c, pytest.raises(UnifiError) as exc:
        c.stamgr("kick-sta", "00:00:5e:00:53:10")
    assert exc.value.rejected and "UnknownStation" in str(exc.value)


@respx.mock
def test_unreachable_is_not_a_rejection():
    respx.post(f"{BASE}/api/auth/login").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(UnifiError) as exc, UnifiClient(BASE, username="janus", password="pw") as c:
        c.list_known()
    assert not exc.value.rejected


@respx.mock
def test_unreachable_after_login_is_not_a_rejection():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=_login_ok())
    respx.get(f"{P}/rest/user").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(UnifiError) as exc, UnifiClient(BASE, username="janus", password="pw") as c:
        c.list_known()
    assert exc.value.status is None


@respx.mock
def test_update_user_puts_only_the_given_fields():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=_login_ok())
    put = respx.put(f"{P}/rest/user/u1").mock(return_value=httpx.Response(200, json=OK))
    with UnifiClient(BASE, username="janus", password="pw") as c:
        c.update_user("u1", {"note": "janus:guest", "noted": True})
    assert json.loads(put.calls[0].request.read()) == {"note": "janus:guest", "noted": True}
    assert put.calls[0].request.headers["x-csrf-token"] == "c1"
