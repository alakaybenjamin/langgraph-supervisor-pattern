from __future__ import annotations

from pydantic import BaseModel


class McpAppPayload(BaseModel):
    """Payload sent to the frontend when an MCP App should be rendered."""

    resource_uri: str
    mcp_endpoint: str
    tool_name: str
    tool_args: dict = {}
