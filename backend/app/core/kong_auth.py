"""Kong Gateway OAuth authentication for Azure OpenAI.

Provides bearer-token authentication via a Kong API Gateway using
OAuth2 client-credentials flow (client_id / client_secret).
Tokens are cached in memory and refreshed automatically.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TOKEN_EXPIRY_BUFFER_SECONDS = 60


class KongGatewayAuth:
    """Singleton-style token cache for Kong Gateway bearer tokens."""

    _cached_token: Optional[str] = None
    _token_expiry_at: Optional[float] = None

    @classmethod
    async def aget_bearer_token(
        cls,
        *,
        force_refresh: bool = False,
    ) -> str:
        """Fetch (or return cached) bearer token from the Federation endpoint."""
        if (
            cls._cached_token
            and not force_refresh
            and cls._token_expiry_at
            and time.time() < cls._token_expiry_at - _TOKEN_EXPIRY_BUFFER_SECONDS
        ):
            return cls._cached_token

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "client_id": settings.KONG_CLIENT_ID,
            "client_secret": settings.KONG_CLIENT_SECRET,
            "grant_type": "client_credentials",
            "scope": "openid email profile",
        }

        logger.info("Requesting Kong Gateway bearer token …")
        async with httpx.AsyncClient(
            timeout=30.0,
            verify=settings.KONG_VERIFY_SSL,
        ) as client:
            response = await client.post(
                settings.FEDERATION_URL, headers=headers, data=data,
            )

        if not response.is_success:
            msg = f"Kong auth failed ({response.status_code}): {response.text}"
            logger.error(msg)
            raise RuntimeError(msg)

        payload = response.json()
        access_token: str = payload["access_token"]
        expires_in = int(payload.get("expires_in", 3600))

        cls._cached_token = access_token
        cls._token_expiry_at = time.time() + expires_in
        logger.info("Kong bearer token obtained (expires in %ds)", expires_in)
        return access_token

    @classmethod
    def get_bearer_token(cls, *, force_refresh: bool = False) -> str:
        """Sync wrapper around :meth:`aget_bearer_token`.

        Safe to call from within a running event loop (uses a new thread
        when necessary).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    cls.aget_bearer_token(force_refresh=force_refresh),
                ).result()

        return asyncio.run(cls.aget_bearer_token(force_refresh=force_refresh))

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the cached token to force a refresh on next request."""
        cls._cached_token = None
        cls._token_expiry_at = None


def get_token_provider() -> Callable[[], str]:
    """Return a ``() -> str`` callable suitable for LangChain's
    ``azure_ad_token_provider`` parameter.

    The callable transparently returns a cached token or fetches a fresh
    one when the current token is about to expire.
    """
    return KongGatewayAuth.get_bearer_token
