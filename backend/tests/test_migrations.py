from collections.abc import Iterator
from contextlib import contextmanager
from datetime import time

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, create_engine, text

from app import models  # noqa: F401
from app.db import Base
from app.notify.store import default_rule_rows
from tests.conftest import TEST_DATABASE_URL


@contextmanager
def _migrated(schema: str) -> Iterator[Connection]:
    eng = create_engine(TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    with eng.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    try:
        with eng.begin() as conn:
            cfg = Config("alembic.ini")
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
        with eng.connect() as conn:
            yield conn
    finally:
        with eng.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        eng.dispose()


def test_migrations_match_models():
    with _migrated("migcheck") as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []


def test_migration_seeds_default_window_and_rules():
    with _migrated("migseed") as conn:
        windows = conn.execute(text("SELECT name, start_time, duration_min, days, enabled, mute_alerts FROM maintenance_windows")).all()
        assert windows == [("Router & modem daily reboot", time(5, 0), 15, 127, True, True)]
        rules = conn.execute(text("SELECT event_type, channel, enabled FROM notification_rules ORDER BY event_type, channel")).all()
        expected = sorted((r["event_type"], r["channel"], r["enabled"]) for r in default_rule_rows())
        assert [tuple(r) for r in rules] == expected


def test_sightings_have_lookup_index():
    with _migrated("migindex") as conn:
        names = {row[0] for row in conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'sightings'"))}
        assert "ix_sightings_mac_source_ts" in names


def _alembic(conn: Connection, action, revision: str) -> None:
    cfg = Config("alembic.ini")
    cfg.attributes["connection"] = conn
    action(cfg, revision)


@contextmanager
def _at_revision(schema: str, revision: str) -> Iterator[Engine]:
    eng = create_engine(TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    with eng.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    try:
        with eng.begin() as conn:
            _alembic(conn, command.upgrade, revision)
        yield eng
    finally:
        with eng.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        eng.dispose()


def _settings(eng: Engine) -> dict:
    with eng.begin() as conn:
        return dict(conn.execute(text("SELECT key, value FROM settings")).all())


def test_migration_0008_preserves_written_macs():
    with _at_revision("mig0008", "0007") as engine:
        with engine.begin() as c:
            c.execute(text("INSERT INTO settings(key, value) VALUES ('pihole.written_macs', '[\"00:00:5E:00:53:10\"]'::jsonb),"
                           " ('network.config', '{\"pihole_url\": \"http://10.0.0.2\", \"subnet\": \"10.0.0.0/24\"}'::jsonb),"
                           " ('pihole.down_since', '\"2026-10-01T00:00:00+00:00\"'::jsonb),"
                           " ('pihole_dns.down_since', '\"2026-10-02T00:00:00+00:00\"'::jsonb),"
                           " ('pihole_dns.last_ok', '\"2026-10-03T00:00:00+00:00\"'::jsonb)"))
        before = _settings(engine)
        with engine.begin() as c:
            _alembic(c, command.upgrade, "0008")
        rows = _settings(engine)
        assert rows["provider.pihole.written_macs"] == ["00:00:5E:00:53:10"]
        assert "pihole.written_macs" not in rows and rows["dhcp.down_since"] == "2026-10-01T00:00:00+00:00"
        assert rows["dns.down_since"] == "2026-10-02T00:00:00+00:00" and rows["dns.last_ok"] == "2026-10-03T00:00:00+00:00"
        assert not {"pihole.down_since", "pihole_dns.down_since", "pihole_dns.last_ok"} & set(rows)
        assert rows["network.config"] == {"subnet": "10.0.0.0/24"}
        assert rows["providers.config"] == {"dhcp": {"kind": "pihole", "config": {"url": "http://10.0.0.2"}},
                                            "dns": {"same_as": "dhcp"}}
        with engine.begin() as c:
            _alembic(c, command.downgrade, "0007")
        assert _settings(engine) == before


def test_migration_0008_without_custom_pihole_url_writes_no_provider_config():
    with _at_revision("mig0008b", "0007") as engine:
        with engine.begin() as c:
            c.execute(text("INSERT INTO settings(key, value) VALUES ('network.config', '{\"subnet\": \"10.0.0.0/24\"}'::jsonb)"))
        with engine.begin() as c:
            _alembic(c, command.upgrade, "0008")
        rows = _settings(engine)
        assert rows == {"network.config": {"subnet": "10.0.0.0/24"}}
        with engine.begin() as c:
            _alembic(c, command.downgrade, "0007")
        assert _settings(engine) == {"network.config": {"subnet": "10.0.0.0/24"}}
