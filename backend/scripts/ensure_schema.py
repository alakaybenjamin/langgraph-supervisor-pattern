"""
Standalone script: ensure the target PostgreSQL schema exists (CREATE SCHEMA IF NOT EXISTS).

Run this *before* Alembic migrations, checkpointer setup, and grant_rw_privileges.
Idempotent and safe to run multiple times.

``DB_SCHEMA`` must be set explicitly in ``.env`` (no default fallback).
If set to ``public``, the script exits successfully without running SQL since
``public`` exists by default in every PostgreSQL database.

Requires admin credentials (``DATABASE_ADMIN_USER`` / ``DATABASE_ADMIN_PASSWORD``).
The RW user must never be used for DDL operations.

Usage
-----
    cd backend
    export $(grep -v '^#' .env | xargs)
    python scripts/ensure_schema.py
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
TARGET_SCHEMA = os.environ.get("DB_SCHEMA", "").strip()


def _redact(url: str) -> str:
    return re.sub(r"(?<=://)[^@]+@", "***@", url)


async def main() -> None:
    if not DATABASE_URL:
        print(
            "ERROR: No admin database URL could be resolved.\n"
            "Set DATABASE_ADMIN_USER + DATABASE_ADMIN_PASSWORD together with "
            "DATABASE_HOSTNAME and DATABASE_NAME.\n"
            "DDL scripts must use admin credentials exclusively.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not TARGET_SCHEMA:
        print(
            "ERROR: DB_SCHEMA is not set.\n"
            "Set DB_SCHEMA in .env to the target schema name "
            "(e.g. DB_SCHEMA=my_app_schema).",
            file=sys.stderr,
        )
        sys.exit(1)

    print("=" * 60)
    print("Ensure PostgreSQL schema exists")
    print(f"DB     : {_redact(DATABASE_URL)} [DATABASE_ADMIN_USER]")
    print(f"Schema : {TARGET_SCHEMA}")
    print("=" * 60)

    if TARGET_SCHEMA == "public":
        print(
            "\nDB_SCHEMA is ``public`` — no CREATE SCHEMA needed "
            "(``public`` exists by default).\n"
        )
        return

    async with await psycopg.AsyncConnection.connect(
        DATABASE_URL, autocommit=True,
    ) as conn:
        await conn.execute(
            psycopg.sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                psycopg.sql.Identifier(TARGET_SCHEMA),
            )
        )

    print(f"\nCREATE SCHEMA IF NOT EXISTS \"{TARGET_SCHEMA}\" — done.\n")


if __name__ == "__main__":
    asyncio.run(main())
