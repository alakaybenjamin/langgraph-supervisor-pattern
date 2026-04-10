from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import set_graph
from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.core.logging import setup_logging
from app.graph.builder import build_graph, shutdown_graph
from app.mcp.registry import mount_mcp_servers, shutdown_mcp_servers, startup_mcp_servers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Starting Data Governance backend...")

    graph = await build_graph()
    set_graph(graph)
    logger.info("LangGraph ready")

    await startup_mcp_servers()
    logger.info("MCP servers ready")

    yield

    await shutdown_mcp_servers()
    await shutdown_graph()
    logger.info("Shutting down...")


app = FastAPI(
    title="Data Governance Chat API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")

mount_mcp_servers(app)
