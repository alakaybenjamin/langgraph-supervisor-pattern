from __future__ import annotations

import logging

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from app.graph.state import AccessRequestState

logger = logging.getLogger(__name__)

MCP_RESOURCE_URI = "ui://search-app/mcp-app.html"
MCP_ENDPOINT = "/mcp/search-app"


def search_app_node(state: AccessRequestState) -> dict:
    result = interrupt({
        "type": "mcp_app",
        "resource_uri": MCP_RESOURCE_URI,
        "mcp_endpoint": MCP_ENDPOINT,
        "tool_name": "search-data-products",
        "tool_args": {
            "filters": {
                "domain": "all",
                "product_type": "all",
            },
        },
        "context": {"mode": "multi_select"},
    })

    action = result.get("action", "") if isinstance(result, dict) else ""

    if action == "user_message":
        logger.info("Free-text during search app: %r", result.get("text", ""))
        return {
            "current_step": "search_app",
            "messages": [AIMessage(
                content="The search panel is still open. Please use it to find and select "
                "your data products, or close the panel to continue."
            )],
        }

    products = []
    if isinstance(result, dict):
        products = result.get("selected_products", result.get("products", []))
    if isinstance(result, list):
        products = result

    logger.info("Search MCP App returned %d product(s)", len(products))

    return {
        "selected_products": products,
        "current_step": "review_cart",
        "messages": [
            AIMessage(content=f"You selected {len(products)} product(s) from the search panel.")
        ],
    }
