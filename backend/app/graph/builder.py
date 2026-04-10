from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.graph.nodes.faq import faq_node
from app.graph.nodes.status_check import status_check_node
from app.graph.state import SupervisorState
from app.graph.subgraphs.request_access.graph import build_request_access_subgraph
from app.graph.supervisor import supervisor_node

logger = logging.getLogger(__name__)

_checkpointer_ctx = None


def _route_supervisor(state: SupervisorState) -> str:
    return END


async def build_graph() -> Any:
    global _checkpointer_ctx

    _checkpointer_ctx = AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL)
    checkpointer = await _checkpointer_ctx.__aenter__()
    await checkpointer.setup()
    logger.info("PostgresSaver checkpointer initialized")

    request_access_subgraph = build_request_access_subgraph().compile(
        checkpointer=True
    )

    builder = StateGraph(SupervisorState)

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("request_access", request_access_subgraph)
    builder.add_node("faq", faq_node)
    builder.add_node("status_check", status_check_node)

    builder.add_edge(START, "supervisor")
    builder.add_edge("faq", "supervisor")
    builder.add_edge("status_check", "supervisor")
    builder.add_edge("request_access", END)
    builder.add_conditional_edges("supervisor", _route_supervisor, [END])

    graph = builder.compile(checkpointer=checkpointer)
    logger.info("Parent graph compiled successfully")
    return graph


async def shutdown_graph() -> None:
    global _checkpointer_ctx
    if _checkpointer_ctx:
        await _checkpointer_ctx.__aexit__(None, None, None)
        _checkpointer_ctx = None
