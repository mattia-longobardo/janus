import ipaddress
import os
from collections.abc import Iterator

import httpcore
import pytest
from fastapi.testclient import TestClient
from httpcore._backends.anyio import AnyIOBackend
from httpcore._backends.sync import SyncBackend
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.config import settings
from app.db import Base, get_db
from app.main import create_app

TEST_DATABASE_URL = os.environ.get(
    "JANUS_TEST_DATABASE_URL", "postgresql+psycopg://janus:janus@localhost:5432/janus_test"
)
TOKEN = "test-token"


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _blocked(host: str, port: int) -> httpcore.ConnectError:
    return httpcore.ConnectError(f"tests never reach the network: blocked connection to {host}:{port} "
                                 "(use a fake, respx or a loopback address)")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Any real httpx connection to a non-loopback host fails at once, before a socket is opened. It is refused
    at the socket layer of httpcore, below httpx and respx: respx-mocked requests and the TestClient never get
    here, and loopback stays allowed. The error is an httpx ConnectError, so the code sees an unreachable host."""
    sync_connect, async_connect = SyncBackend.connect_tcp, AnyIOBackend.connect_tcp

    def connect_tcp(self, host, port, *args, **kwargs):
        if not _is_loopback(host):
            raise _blocked(host, port)
        return sync_connect(self, host, port, *args, **kwargs)

    async def connect_tcp_async(self, host, port, *args, **kwargs):
        if not _is_loopback(host):
            raise _blocked(host, port)
        return await async_connect(self, host, port, *args, **kwargs)

    monkeypatch.setattr(SyncBackend, "connect_tcp", connect_tcp)
    monkeypatch.setattr(AnyIOBackend, "connect_tcp", connect_tcp_async)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = create_engine(TEST_DATABASE_URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    trans.rollback()
    conn.close()


@pytest.fixture
def client(db, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setattr(settings, "internal_token", TOKEN)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app, headers={"X-Janus-Internal-Token": TOKEN}) as test_client:
        yield test_client
