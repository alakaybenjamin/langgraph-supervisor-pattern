from __future__ import annotations

"""Parent supervisor graph compose.

Layout:

    START
      -> recover_state
      -> supervisor_router
           -> request_access_subgraph  (compiled StateGraph as a node)
           -> faq_kb_agent
           -> general_faq_tavily_agent
           -> status_agent
           -> END (direct reply fallback)

Checkpointing is configured on the parent graph only. Since the request-access
subgraph is attached as a compiled node, it inherits the parent's checkpointer
and shares the same ``thread_id``.
"""

import logging
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.postgres import AsyncPostgresStore

from app.core.config import settings
from app.graph.faq_agents import faq_kb_agent, general_faq_tavily_agent
from app.graph.nodes.status_check import status_check_node
from app.graph.parent_supervisor import recover_state_node, supervisor_router
from app.graph.state import AppState
from app.graph.subgraphs.request_access import build_request_access_subgraph

logger = logging.getLogger(__name__)

_checkpointer_ctx = None
_store_ctx = None


async def build_graph() -> Any:
    global _checkpointer_ctx, _store_ctx

    _checkpointer_ctx = AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL)
    checkpointer = await _checkpointer_ctx.__aenter__()
    logger.info("PostgresSaver checkpointer connected")

    _store_ctx = AsyncPostgresStore.from_conn_string(settings.DATABASE_URL)
    store = await _store_ctx.__aenter__()
    await store.setup()
    logger.info("PostgresStore connected for cross-session memory")

    ra_subgraph = build_request_access_subgraph()

    builder = StateGraph(AppState)

    builder.add_node("recover_state", recover_state_node)
    builder.add_node("supervisor_router", supervisor_router)
    builder.add_node("request_access_subgraph", ra_subgraph)
    builder.add_node("faq_kb_agent", faq_kb_agent)
    builder.add_node("general_faq_tavily_agent", general_faq_tavily_agent)
    builder.add_node("status_agent", status_check_node)

    builder.add_edge(START, "recover_state")
    builder.add_edge("recover_state", "supervisor_router")

    # Terminal edges for every supervisor branch.
    builder.add_edge("request_access_subgraph", END)
    builder.add_edge("faq_kb_agent", END)
    builder.add_edge("general_faq_tavily_agent", END)
    builder.add_edge("status_agent", END)

    graph = builder.compile(checkpointer=checkpointer, store=store)
    logger.info("Parent graph compiled")
    return graph


async def shutdown_graph() -> None:
    global _checkpointer_ctx, _store_ctx
    if _checkpointer_ctx:
        await _checkpointer_ctx.__aexit__(None, None, None)
        _checkpointer_ctx = None
    if _store_ctx:
        await _store_ctx.__aexit__(None, None, None)
        _store_ctx = None
