"""
Standalone script: initialise (or verify) LangGraph's checkpointer tables
inside the target schema.

Usage
-----
    cd backend
    export $(grep -v '^#' .env | xargs)
    python scripts/setup_checkpointer.py

What it does
------------
1. Connects to the database using admin credentials (required).
2. Reads the current contents of ``<schema>.checkpoint_migrations`` -- BEFORE snapshot.
3. Calls AsyncPostgresSaver.setup() with ``search_path=<schema>`` so all
   checkpointer tables land in that schema (idempotent).
4. Reads ``<schema>.checkpoint_migrations`` again and prints the AFTER snapshot,
   showing any new rows that were inserted.

Nothing is changed if the schema is already up to date.
This script is safe to run multiple times.

Why a separate script?
----------------------
LangGraph owns its checkpoint tables; Alembic owns the application tables.
Running this script independently (e.g. as a pre-deploy step) keeps the two
migration paths clearly separated and gives a full audit trail before the
app process starts.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, quote, quote_plus, urlencode, urlparse, urlunparse

import psycopg
from psycopg.rows import dict_row

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


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
TARGET_SCHEMA = os.environ.get("DB_SCHEMA", "public")


def _with_search_path(url: str, schema: str) -> str:
    """Return a copy of *url* with ``options=-c search_path=<schema>`` set."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs["options"] = [f'-c search_path="{schema}" -c lock_timeout=5000']
    if "connect_timeout" not in qs:
        qs["connect_timeout"] = ["10"]
    return urlunparse(parsed._replace(query=urlencode(qs, doseq=True, quote_via=quote)))


async def _read_migrations(conn) -> list[dict]:
    """Return rows from checkpoint_migrations, or [] if the table does not exist yet."""
    try:
        rows = await (
            await conn.execute(
                f'SELECT * FROM "{TARGET_SCHEMA}".checkpoint_migrations ORDER BY v ASC'
            )
        ).fetchall()
        return list(rows)
    except psycopg.errors.UndefinedTable:
        await conn.rollback()
        return []


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

    print("=" * 60)
    print("LangGraph checkpointer setup")
    print(f"DB     : {_redact(DATABASE_URL)} [DATABASE_ADMIN_USER]")
    print(f"Schema : {TARGET_SCHEMA}")
    print("=" * 60)

    conn_str = _with_search_path(DATABASE_URL, TARGET_SCHEMA)

    # -- BEFORE snapshot -------------------------------------------------
    async with await psycopg.AsyncConnection.connect(
        DATABASE_URL, row_factory=dict_row,
    ) as probe:
        before = await _read_migrations(probe)

    if before:
        print(f"\nBEFORE: {len(before)} migration(s) already applied:")
        for row in before:
            print(f"  [v={row['v']}]")
    else:
        print(
            f"\nBEFORE: {TARGET_SCHEMA}.checkpoint_migrations does not exist yet "
            "(fresh install)."
        )

    # -- Run setup() -----------------------------------------------------
    print(f"\nRunning AsyncPostgresSaver.setup() in schema '{TARGET_SCHEMA}' ...")
    async with AsyncPostgresSaver.from_conn_string(conn_str) as checkpointer:
        await checkpointer.setup()
    print("setup() completed.")

    # -- AFTER snapshot --------------------------------------------------
    async with await psycopg.AsyncConnection.connect(
        DATABASE_URL, row_factory=dict_row,
    ) as probe:
        after = await _read_migrations(probe)

    print(f"\nAFTER : {len(after)} migration(s) recorded:")
    for row in after:
        print(f"  [v={row['v']}]")

    new_rows = [r for r in after if r not in before]
    if new_rows:
        print(f"\n  {len(new_rows)} new migration(s) applied this run.")
    else:
        print("\n  No new migrations -- schema was already up to date.")

    print("\nDone.\n")


if __name__ == "__main__":
    asyncio.run(main())
