from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401
from app.config import settings
from app.db import Base

config = context.config
target_metadata = Base.metadata


def _run(connection) -> None:
    # per migration: 0009 commits mid-run (ALTER TYPE ... ADD VALUE), so each file owns its transaction
    context.configure(connection=connection, target_metadata=target_metadata, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        _run(conn)
