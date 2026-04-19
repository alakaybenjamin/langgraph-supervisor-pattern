from __future__ import annotations

"""Pre-fetch MCP facet chips so step UIs match the 3rd-party catalog.

Runs on subgraph entry (and once per request-access flow). Calls the MCP
``list_facets`` tool and caches the response under
``state.mcp_facet_cache``. Downstream consumers — the conversational
``narrow_search`` subagent (system prompt) and the legacy chip nodes
(``choose_domain`` / ``choose_anonymization``) — read from that cache
so any value the user can land on matches the ids the MCP ``search``
tool will accept.

After prefetch we re-enter ``run_current_workflow_step`` rather than
hard-coding the next node so the default flow (narrowing) and explicit
nav targets (chips) both work.

If the MCP server is unreachable we simply skip writing the cache — the
chip nodes fall back to hardcoded defaults and the narrowing subagent
falls back to listing ``(unknown)`` in its system prompt.
"""

import logging

from langgraph.types import Command

from app.graph.state import AppState
from app.service import mcp_search_client

logger = logging.getLogger(__name__)


async def mcp_prefetch_facets(state: AppState) -> Command:
    """Fetch + cache canonical facet chips from the MCP search server.

    Always writes ``mcp_facet_cache`` (using an empty-but-shaped dict on
    failure) so ``_dispatch_fresh``'s ``is None`` guard never re-enters
    this node twice in a session.
    """
    if state.get("mcp_facet_cache") is not None:
        logger.debug("mcp_prefetch_facets: cache present, skipping fetch")
        return Command(goto="run_current_workflow_step")

    facets = await mcp_search_client.list_facets()
    if not facets:
        logger.info(
            "mcp_prefetch_facets: no facets returned (server unreachable?) "
            "— writing empty cache sentinel",
        )
        return Command(
            update={"mcp_facet_cache": {"domains": [], "anonymization": []}},
            goto="run_current_workflow_step",
        )

    logger.info(
        "mcp_prefetch_facets: cached %d domain(s), %d anonymization level(s)",
        len(facets.get("domains") or []),
        len(facets.get("anonymization") or []),
    )
    return Command(
        update={"mcp_facet_cache": facets},
        goto="run_current_workflow_step",
    )
