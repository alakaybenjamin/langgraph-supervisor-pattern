"""@file mcp_search_client.py
@brief Thin async client for the data-product search MCP server.

Speaks the MCP streamable-HTTP protocol and treats the search-app server as
an external third-party data catalog. Exposes two typed helpers used by the
request-access subgraph:

- :func:`search` — free-text + structured filters (domains, anonymization,
  study_id), returns normalized product dicts.
- :func:`list_facets` — fetches the canonical domain / anonymization chips
  so the UI can render filter options that match what ``search`` expects.

Each call opens its own short-lived MCP session (the server is configured
``stateless=True``). That keeps the wiring simple and side-effect free; if
latency becomes an issue a connection pool can be layered on top without
changing the call sites.

Both helpers fall back to safe empty defaults and log a warning on any
transport or protocol error — callers should never raise out of the search
path just because the MCP server is briefly unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.core.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 10.0


def _structured(result: Any) -> dict:
    """Extract ``structuredContent`` from an MCP CallToolResult, safely."""
    sc = getattr(result, "structuredContent", None)
    if isinstance(sc, dict):
        return sc
    return {}


async def _call_tool(tool_name: str, arguments: dict[str, Any]) -> dict:
    """Open a short-lived MCP session and invoke a single tool.

    :param tool_name:  Tool to call (e.g. ``search``, ``list_facets``).
    :param arguments:  Arguments dict passed through unchanged.
    :returns:          The tool's ``structuredContent`` dict, or ``{}`` on
                       transport / protocol failure.
    """
    url = settings.MCP_SEARCH_URL
    timeout = settings.MCP_SEARCH_TIMEOUT_SECONDS or _DEFAULT_TIMEOUT_SECONDS
    try:
        async with streamablehttp_client(url, timeout=timeout) as (
            read_stream,
            write_stream,
            _info,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                return _structured(result)
    except Exception:  # noqa: BLE001 — we always want to degrade gracefully
        logger.exception(
            "mcp_search_client: call to %s failed (url=%s)", tool_name, url
        )
        return {}


async def list_facets() -> dict:
    """@brief Fetch the canonical facet chips from the MCP server.

    :returns: Dict with keys ``domains`` and ``anonymization`` — each a list
              of ``{"id", "label"}`` dicts. Returns an empty dict if the
              server is unreachable.
    """
    return await _call_tool("list_facets", {})


async def search(
    *,
    search_text: str = "*",
    domains: list[str] | None = None,
    anonymization: str | None = None,
    study_id: str | None = None,
) -> list[dict]:
    """@brief Call the MCP ``search`` tool with structured filters.

    Keys with empty values are omitted from the request so the server does
    not treat them as explicit filters. Callers pass ``search_text='*'``
    (the server default) when they only want filter-driven results.

    :param search_text:  Free-text query; ``'*'`` or empty matches all.
    :param domains:      Multi-select domain ids (``[]`` or ``None`` skips).
    :param anonymization: Single anonymization level (``None`` skips).
    :param study_id:     Free-text study id substring (``None`` skips).
    :returns:            List of raw product dicts as returned by the
                         server's ``structuredContent.products``. Never
                         raises — returns ``[]`` on error.
    """
    filters: dict[str, Any] = {}
    if domains:
        filters["domains"] = [d for d in domains if d and d != "all"]
    if anonymization:
        filters["anonymization"] = anonymization
    if study_id:
        filters["study_id"] = study_id

    args: dict[str, Any] = {"search_text": (search_text or "*")}
    if filters:
        args["filters"] = filters

    data = await _call_tool("search", args)
    products = data.get("products")
    if not isinstance(products, list):
        return []
    return products
