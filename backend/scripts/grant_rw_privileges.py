"""
Standalone script: grant read-write privileges on all schema tables/sequences
to the application RW user.

Run this script after EITHER Alembic migrations OR checkpointer setup -- it is
idempotent and safe to run multiple times.

Covers:
  - All existing tables  (SELECT, INSERT, UPDATE, DELETE)
  - All existing sequences (USAGE, SELECT)
  - Future tables and sequences via ALTER DEFAULT PRIVILEGES

Usage
-----
    cd backend
    export $(grep -v '^#' .env | xargs)
    python scripts/grant_rw_privileges.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus

import psycopg

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _build_pg_url(user_env: str, password_env: str) -> str:
    """Reconstruct a PostgreSQL URL from the atomic DATABASE_* environment variables."""
    host = os.environ.get("DATABASE_HOSTNAME", "")
    port = os.environ.get("DATABASE_PORT", "5432")
    name = os.environ.get("DATABASE_NAME", "")
    user = os.environ.get(user_env, "")
    pwd = os.environ.get(password_env, "")
    if host and user and name:
        return f"postgresql://{quote_plus(user)}:{quote_plus(pwd)}@{host}:{port}/{name}"
    return ""


DATABASE_URL = _build_pg_url("DATABASE_ADMIN_USER", "DATABASE_ADMIN_PASSWORD")
RW_USER = os.environ.get("DATABASE_USER", "")
TARGET_SCHEMA = os.environ.get("DB_SCHEMA", "public")


def _redact(url: str) -> str:
    return re.sub(r"(?<=://)[^@]+@", "***@", url)


async def main() -> None:
    if not DATABASE_URL:
        print(
            "ERROR: No admin database URL could be resolved.\n"
            "Set DATABASE_ADMIN_USER + DATABASE_ADMIN_PASSWORD together with "
            "DATABASE_HOSTNAME and DATABASE_NAME.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not RW_USER:
        print("ERROR: DATABASE_USER is not set.", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("RW privilege grant")
    print(f"DB     : {_redact(DATABASE_URL)}")
    print(f"Schema : {TARGET_SCHEMA}")
    print(f"RW user: {RW_USER}")
    print("=" * 60)

    async with await psycopg.AsyncConnection.connect(
        DATABASE_URL, autocommit=True,
    ) as conn:
        schema = TARGET_SCHEMA

        # -- Schema-level ---------------------------------------------------
        await conn.execute(
            psycopg.sql.SQL("GRANT USAGE ON SCHEMA {schema} TO {user}").format(
                schema=psycopg.sql.Identifier(schema),
                user=psycopg.sql.Identifier(RW_USER),
            )
        )
        print(f"  GRANT USAGE ON SCHEMA {schema}")

        # -- All existing tables --------------------------------------------
        await conn.execute(
            psycopg.sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE"
                " ON ALL TABLES IN SCHEMA {schema} TO {user}"
            ).format(
                schema=psycopg.sql.Identifier(schema),
                user=psycopg.sql.Identifier(RW_USER),
            )
        )
        print(f"  GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema}")

        # -- All existing sequences -----------------------------------------
        await conn.execute(
            psycopg.sql.SQL(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {user}"
            ).format(
                schema=psycopg.sql.Identifier(schema),
                user=psycopg.sql.Identifier(RW_USER),
            )
        )
        print(f"  GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema}")

        # -- Default privileges (future tables + sequences) -----------------
        await conn.execute(
            psycopg.sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA {schema}"
                " GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {user}"
            ).format(
                schema=psycopg.sql.Identifier(schema),
                user=psycopg.sql.Identifier(RW_USER),
            )
        )
        print(f"  ALTER DEFAULT PRIVILEGES ON TABLES in {schema}")

        await conn.execute(
            psycopg.sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA {schema}"
                " GRANT USAGE, SELECT ON SEQUENCES TO {user}"
            ).format(
                schema=psycopg.sql.Identifier(schema),
                user=psycopg.sql.Identifier(RW_USER),
            )
        )
        print(f"  ALTER DEFAULT PRIVILEGES ON SEQUENCES in {schema}")

        # -- Confirm which tables were granted ------------------------------
        result = await conn.execute(
            psycopg.sql.SQL(
                "SELECT tablename FROM pg_tables"
                " WHERE schemaname = {schema} ORDER BY tablename"
            ).format(schema=psycopg.sql.Literal(schema))
        )
        tables = [row[0] for row in await result.fetchall()]
        print(f"\n  Tables in schema ({len(tables)}):")
        for t in tables:
            print(f"    - {t}")

    print("\nDone.\n")


if __name__ == "__main__":
    asyncio.run(main())
