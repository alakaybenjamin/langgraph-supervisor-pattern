from logging.config import fileConfig

from sqlalchemy import create_engine, pool, text

from alembic import context

from app.core.config import settings
from app.db.base import Base

import app.models.user  # noqa: F401
import app.models.thread  # noqa: F401
import app.models.access_request  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_db_schema = settings.DB_SCHEMA if settings.DB_SCHEMA != "public" else None


def run_migrations_offline() -> None:
    context.configure(
        url=settings.sqlalchemy_admin_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=_db_schema,
        include_schemas=bool(_db_schema),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        settings.sqlalchemy_admin_database_url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        if _db_schema:
            connection.execute(text(f'SET search_path TO "{_db_schema}"'))
            connection.dialect.default_schema_name = _db_schema

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=_db_schema,
            include_schemas=bool(_db_schema),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
