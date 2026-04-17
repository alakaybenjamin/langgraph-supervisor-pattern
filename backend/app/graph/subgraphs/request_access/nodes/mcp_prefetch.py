from __future__ import annotations

"""Pre-fetch MCP facet chips so step UIs match the 3rd-party catalog.

Runs on subgraph entry (and once per request-access flow). Calls the MCP
``list_facets`` tool and caches the response under
``state.mcp_facet_cache``. Downstream HITL steps (``choose_domain``,
``choose_anonymization``) read from that cache so the chips presented to
the user always match the ids that the MCP ``search`` tool will accept.

If the MCP server is unreachable we simply skip writing the cache — the
step nodes then fall back to their hardcoded defaults without error.
"""

import logging

from langgraph.types import Command

from app.graph.state import AppState
from app.service import mcp_search_client

logger = logging.getLogger(__name__)


async def mcp_prefetch_facets(state: AppState) -> Command:
    """Fetch + cache canonical facet chips from the MCP search server."""
    if state.get("mcp_facet_cache"):
        logger.debug("mcp_prefetch_facets: cache present, skipping fetch")
        return Command(goto="choose_domain")

    facets = await mcp_search_client.list_facets()
    if not facets:
        logger.info(
            "mcp_prefetch_facets: no facets returned (server unreachable?) "
            "— falling back to hardcoded chips",
        )
        return Command(goto="choose_domain")

    logger.info(
        "mcp_prefetch_facets: cached %d domain(s), %d anonymization level(s)",
        len(facets.get("domains") or []),
        len(facets.get("anonymization") or []),
    )
    return Command(
        update={"mcp_facet_cache": facets},
        goto="choose_domain",
    )
