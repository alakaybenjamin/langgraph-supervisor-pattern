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
    DATABASE_USER: str = ""
    DATABASE_PASSWORD: str = ""
    DB_SCHEMA: str = "public"

    TAVILY_API_KEY: str = ""

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

    def _base_dsn(self, driver: str = "postgresql") -> str:
        userinfo = ""
        if self.DATABASE_USER:
            userinfo = self.DATABASE_USER
            if self.DATABASE_PASSWORD:
                userinfo += f":{self.DATABASE_PASSWORD}"
            userinfo += "@"
        return (
            f"{driver}://{userinfo}"
            f"{self.DATABASE_HOSTNAME}:{self.DATABASE_PORT}"
            f"/{self.DATABASE_NAME}"
        )

    @property
    def DATABASE_URL(self) -> str:
        """Libpq-style DSN for raw ``psycopg`` APIs (e.g. LangGraph checkpointer).

        Plain ``postgresql://`` — do not pass this to SQLAlchemy's sync
        ``create_engine``; it defaults to the ``psycopg2`` driver. Use
        :attr:`sqlalchemy_sync_database_url` for Alembic.

        Includes ``?options=-csearch_path=<schema>`` when DB_SCHEMA is not
        the default ``public``.
        """
        url = self._base_dsn("postgresql")
        if self.DB_SCHEMA and self.DB_SCHEMA != "public":
            url += self._search_path_option()
        return url

    @property
    def sqlalchemy_sync_database_url(self) -> str:
        """Sync URL for Alembic / SQLAlchemy using psycopg v3.

        ``postgresql+psycopg://`` selects the installed ``psycopg`` package.
        A bare ``postgresql://`` URL makes SQLAlchemy import ``psycopg2``,
        which is not a project dependency.
        """
        url = self._base_dsn("postgresql+psycopg")
        if self.DB_SCHEMA and self.DB_SCHEMA != "public":
            url += self._search_path_option()
        return url

    def _search_path_option(self) -> str:
        """URL query-string fragment that sets ``search_path`` via libpq options.

        The schema name is double-quoted so names with hyphens or other
        special characters are handled correctly by PostgreSQL.
        """
        from urllib.parse import quote

        return "?options=" + quote(f'-csearch_path="{self.DB_SCHEMA}"')

    @property
    def async_database_url(self) -> str:
        """Async PostgreSQL DSN for SQLAlchemy + asyncpg.

        Schema is set via the asyncpg ``server_settings`` connect arg
        rather than query-string options, so this URL has no schema suffix.
        """
        return self._base_dsn("postgresql+asyncpg")


settings = Settings()
