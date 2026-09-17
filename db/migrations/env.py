from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# make the workspace python packages importable without install
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python" / "openquyhoach_core" / "src"))

from openquyhoach_core.db import Base  # noqa: E402
import openquyhoach_core.models  # noqa: E402,F401 — register all tables

config = context.config

url = os.environ.get("OQH_DATABASE_URL")
if not url:
    from openquyhoach_core.settings import get_settings

    url = get_settings().database_url
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
