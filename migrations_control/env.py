from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.control_models import ControlBase


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

configured_url = os.getenv("SMART_CRM_CONTROL_DATABASE_URL")
if configured_url:
    config.set_main_option("sqlalchemy.url", configured_url.replace("%", "%%"))

target_metadata = ControlBase.metadata


def configure(connection=None, *, url=None) -> None:  # noqa: ANN001
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        version_table="alembic_control_version",
        compare_type=True,
        literal_binds=url is not None,
        dialect_opts={"paramstyle": "named"} if url is not None else None,
    )


def run_migrations_offline() -> None:
    configure(url=config.get_main_option("sqlalchemy.url"))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        configure(connection=supplied_connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
