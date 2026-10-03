"""network providers: per-role settings keys

Revision ID: 0008
Revises: 0007
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

RENAMES = (
    ("pihole.written_macs", "provider.pihole.written_macs"),
    ("pihole.down_since", "dhcp.down_since"),
    ("pihole_dns.down_since", "dns.down_since"),
    ("pihole_dns.last_ok", "dns.last_ok"),
)
NETWORK_KEY = "network.config"
PROVIDERS_KEY = "providers.config"


def _get(conn: sa.Connection, key: str) -> object:
    return conn.execute(sa.text("SELECT value FROM settings WHERE key = :k"), {"k": key}).scalar()


def _put(conn: sa.Connection, key: str, value: object) -> None:
    conn.execute(sa.text("INSERT INTO settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
                         "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"), {"k": key, "v": json.dumps(value)})


def _rename(conn: sa.Connection, old: str, new: str) -> None:
    conn.execute(sa.text("DELETE FROM settings WHERE key = :new AND EXISTS (SELECT 1 FROM settings WHERE key = :old)"),
                 {"old": old, "new": new})
    conn.execute(sa.text("UPDATE settings SET key = :new WHERE key = :old"), {"old": old, "new": new})


def upgrade() -> None:
    conn = op.get_bind()
    for old, new in RENAMES:
        _rename(conn, old, new)
    network = _get(conn, NETWORK_KEY)
    if isinstance(network, dict) and "pihole_url" in network:
        url = network.pop("pihole_url")
        _put(conn, NETWORK_KEY, network)
        _put(conn, PROVIDERS_KEY, {"dhcp": {"kind": "pihole", "config": {"url": url}}, "dns": {"same_as": "dhcp"}})


def downgrade() -> None:
    conn = op.get_bind()
    for old, new in RENAMES:
        _rename(conn, new, old)
    providers = _get(conn, PROVIDERS_KEY)
    dhcp = providers.get("dhcp") if isinstance(providers, dict) else None
    config = dhcp.get("config") if isinstance(dhcp, dict) and dhcp.get("kind") == "pihole" else None
    if isinstance(config, dict) and config.get("url"):
        network = _get(conn, NETWORK_KEY)
        _put(conn, NETWORK_KEY, {**(network if isinstance(network, dict) else {}), "pihole_url": config["url"]})
    conn.execute(sa.text("DELETE FROM settings WHERE key = :k"), {"k": PROVIDERS_KEY})
