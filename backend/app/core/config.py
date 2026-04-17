from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # "openai" = direct OpenAI API  |  "azure_kong" = Azure OpenAI via Kong Gateway
    LLM_PROVIDER: str = "openai"

    # --- OpenAI (used when LLM_PROVIDER=openai) ---
    OPENAI_API_KEY: str = ""
    MODEL_NAME: str = "gpt-4o"
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # --- Kong Gateway / Azure OpenAI (used when LLM_PROVIDER=azure_kong) ---
    KONG_CLIENT_ID: str = ""
    KONG_CLIENT_SECRET: str = ""
    KONG_BASE_URL: str = ""
    KONG_DEPLOYMENT: str = "gpt-4o"
    KONG_MINI_DEPLOYMENT: str = "gpt-4o-mini"
    KONG_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-small"
    KONG_API_VERSION: str = "2025-01-01-preview"
    FEDERATION_URL: str = ""
    KONG_VERIFY_SSL: bool = True

    # --- PostgreSQL ---
    DATABASE_HOSTNAME: str = "localhost"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str = "postgres"
    # Read-write user — used by the running app at runtime
    DATABASE_RW_USER: str = ""
    DATABASE_RW_PASSWORD: str = ""
    # Admin user — DDL only (Alembic migrations, checkpointer setup), never deployed
    DATABASE_ADMIN_USER: str = ""
    DATABASE_ADMIN_PASSWORD: str = ""
    DB_SCHEMA: str = "public"

    TAVILY_API_KEY: str = ""

    # --- MCP search-app server (simulated 3rd-party data catalog) -----------
    # Streamable-HTTP endpoint that the request-access subgraph calls for
    # product search and facet discovery. Defaults to the loopback mount in
    # this FastAPI process; point at a different host to use a truly
    # external MCP server.
    MCP_SEARCH_URL: str = "http://localhost:8000/mcp/search-app"
    MCP_SEARCH_TIMEOUT_SECONDS: float = 10.0

    @model_validator(mode="after")
    def _check_provider_credentials(self) -> Settings:
        if self.LLM_PROVIDER == "openai" and not self.OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY is required when LLM_PROVIDER=openai"
            )
        if self.LLM_PROVIDER == "azure_kong":
            missing = [
                name
                for name, val in [
                    ("KONG_CLIENT_ID", self.KONG_CLIENT_ID),
                    ("KONG_CLIENT_SECRET", self.KONG_CLIENT_SECRET),
                    ("KONG_BASE_URL", self.KONG_BASE_URL),
                    ("FEDERATION_URL", self.FEDERATION_URL),
                ]
                if not val
            ]
            if missing:
                raise ValueError(
                    f"LLM_PROVIDER=azure_kong requires: {', '.join(missing)}"
                )
        return self

    def _base_dsn(
        self, driver: str = "postgresql", *, user: str = "", password: str = "",
    ) -> str:
        """Build a DSN from the shared host/port/name and the given credentials."""
        user = user or self.DATABASE_RW_USER
        password = password or self.DATABASE_RW_PASSWORD
        userinfo = ""
        if user:
            userinfo = user
            if password:
                userinfo += f":{password}"
            userinfo += "@"
        return (
            f"{driver}://{userinfo}"
            f"{self.DATABASE_HOSTNAME}:{self.DATABASE_PORT}"
            f"/{self.DATABASE_NAME}"
        )

    # -- RW URLs (runtime app, LangGraph checkpointer) -----------------------

    @property
    def DATABASE_URL(self) -> str:
        """Libpq-style DSN using **RW** credentials.

        Plain ``postgresql://`` — do not pass this to SQLAlchemy's sync
        ``create_engine`` (it defaults to psycopg2). Use
        :attr:`sqlalchemy_admin_database_url` for Alembic.
        """
        url = self._base_dsn("postgresql")
        if self.DB_SCHEMA and self.DB_SCHEMA != "public":
            url += self._search_path_option()
        return url

    @property
    def async_database_url(self) -> str:
        """Async DSN (``postgresql+asyncpg://``) using **RW** credentials.

        Schema is set via the asyncpg ``server_settings`` connect arg
        rather than query-string options, so this URL has no schema suffix.
        """
        return self._base_dsn("postgresql+asyncpg")

    # -- Admin URLs (Alembic DDL — admin credentials only) ----------------------

    @property
    def sqlalchemy_admin_database_url(self) -> str:
        """Sync URL for Alembic DDL using **admin** credentials and psycopg v3.

        Requires ``DATABASE_ADMIN_USER`` to be set; raises if missing.
        """
        if not self.DATABASE_ADMIN_USER:
            raise ValueError(
                "DATABASE_ADMIN_USER is required for DDL operations "
                "(Alembic migrations). Set it in .env."
            )
        url = self._base_dsn(
            "postgresql+psycopg",
            user=self.DATABASE_ADMIN_USER,
            password=self.DATABASE_ADMIN_PASSWORD,
        )
        if self.DB_SCHEMA and self.DB_SCHEMA != "public":
            url += self._search_path_option()
        return url

    # -- Helpers --------------------------------------------------------------

    def _search_path_option(self) -> str:
        """URL query-string fragment that sets ``search_path`` via libpq options.

        The schema name is double-quoted so names with hyphens or other
        special characters are handled correctly by PostgreSQL.
        """
        from urllib.parse import quote

        return "?options=" + quote(f'-csearch_path="{self.DB_SCHEMA}"')


settings = Settings()
