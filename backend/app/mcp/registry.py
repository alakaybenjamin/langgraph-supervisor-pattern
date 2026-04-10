"""
MCP Server Registry.

Discovers MCP server folders under app/mcp/ and mounts each one
on the FastAPI application at /mcp/{server-name}.

Uses a raw ASGI middleware approach to avoid Starlette's trailing-slash
redirect that breaks MCP clients.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from fastapi import FastAPI
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

logger = logging.getLogger(__name__)

MCP_DIR = Path(__file__).parent

CORS_HEADERS: list[tuple[bytes, bytes]] = [
    (b"access-control-allow-origin", b"*"),
    (b"access-control-allow-methods", b"GET, POST, PUT, DELETE, OPTIONS"),
    (b"access-control-allow-headers", b"*"),
    (b"access-control-expose-headers", b"*"),
]

_servers: dict[str, StreamableHTTPSessionManager] = {}
_contexts: dict[str, object] = {}


def _load_server_module(folder_name: str):
    server_path = MCP_DIR / folder_name / "server.py"
    spec = importlib.util.spec_from_file_location(f"mcp_{folder_name}", server_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.create_server()


MCP_APPS = [
    {"name": "question-form", "folder": "question-form-app-python"},
    {"name": "search-app", "folder": "search-app"},
]


async def startup_mcp_servers() -> None:
    for app_def in MCP_APPS:
        name = app_def["name"]
        folder = app_def["folder"]
        try:
            server = _load_server_module(folder)
            manager = StreamableHTTPSessionManager(
                app=server,
                stateless=True,
                json_response=True,
            )
            ctx = manager.run()
            await ctx.__aenter__()
            _servers[name] = manager
            _contexts[name] = ctx
            logger.info("MCP %s server started (from %s)", name, folder)
        except Exception:
            logger.exception("Failed to start MCP server %s", name)


async def shutdown_mcp_servers() -> None:
    for name, ctx in _contexts.items():
        try:
            await ctx.__aexit__(None, None, None)
            logger.info("MCP %s server shut down", name)
        except Exception:
            logger.exception("Error shutting down MCP %s", name)
    _servers.clear()
    _contexts.clear()


def mount_mcp_servers(app: FastAPI) -> None:
    original_app = app.router

    prefixes = {f"/mcp/{a['name']}": a["name"] for a in MCP_APPS}

    async def mcp_middleware(scope: dict, receive, send):
        if scope["type"] == "http":
            path: str = scope.get("path", "")
            for prefix, name in prefixes.items():
                if path == prefix or path == prefix + "/":
                    await _handle_mcp(name, scope, receive, send)
                    return

        await original_app(scope, receive, send)

    app.router = mcp_middleware  # type: ignore[assignment]

    for prefix in prefixes:
        logger.info("Mounted MCP server at %s (middleware)", prefix)


async def _handle_mcp(name: str, scope: dict, receive, send):
    method = scope.get("method", "")

    if method == "OPTIONS":
        await send({"type": "http.response.start", "status": 204, "headers": CORS_HEADERS})
        await send({"type": "http.response.body", "body": b""})
        return

    manager = _servers.get(name)
    if manager is None:
        await send({"type": "http.response.start", "status": 503, "headers": []})
        await send({"type": "http.response.body", "body": b"MCP server not ready"})
        return

    original_send = send

    async def send_with_cors(message: dict):
        if message["type"] == "http.response.start":
            headers = list(message.get("headers", []))
            headers.extend(CORS_HEADERS)
            message = {**message, "headers": headers}
        await original_send(message)

    rewritten_scope = {**scope, "path": "/mcp"}
    await manager.handle_request(rewritten_scope, receive, send_with_cors)
