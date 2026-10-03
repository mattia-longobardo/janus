import socket

import httpx
import pytest

from app.providers.pihole.client import PiholeClient, PiholeError


@pytest.fixture
def no_sockets(monkeypatch):
    """Fails the test if anything gets as far as opening a TCP connection."""
    def refuse(*args, **kwargs):
        raise AssertionError("a real socket connection was attempted")
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def test_real_request_to_a_lan_host_is_blocked_without_traffic(no_sockets):
    with pytest.raises(httpx.ConnectError, match="tests never reach the network: blocked connection to 192.168.1.220"):
        httpx.get("http://192.168.1.220:1000/api/auth", timeout=30)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_real_async_request_to_a_lan_host_is_blocked_without_traffic(no_sockets):
    async with httpx.AsyncClient(timeout=30) as http:
        with pytest.raises(httpx.ConnectError, match="blocked connection to 192.168.1.220"):
            await http.get("http://192.168.1.220:1000/")


def test_hostnames_are_blocked_too(no_sockets):
    with pytest.raises(httpx.ConnectError, match="blocked connection to pihole.lan"):
        httpx.get("http://pihole.lan/")


def test_pihole_client_sees_an_unreachable_host(no_sockets):
    with pytest.raises(PiholeError, match="Pi-hole unreachable: tests never reach the network"):
        PiholeClient("http://192.168.1.220:1000", "pw").get_config("dhcp")


def test_loopback_is_still_allowed():
    with pytest.raises(httpx.ConnectError) as exc:
        httpx.get("http://127.0.0.1:9/", timeout=5)   # nothing listens: refused by the OS, not by the guard
    assert "tests never reach the network" not in str(exc.value)
