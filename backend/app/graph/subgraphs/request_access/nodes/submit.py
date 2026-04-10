from __future__ import annotations

import logging
import uuid

from langchain_core.messages import AIMessage

from app.graph.state import AccessRequestState

logger = logging.getLogger(__name__)


def submit_node(state: AccessRequestState) -> dict:
    products = state.get("selected_products", [])
    form_drafts = state.get("form_drafts", {})

    request_id = f"REQ-{uuid.uuid4().hex[:6].upper()}"

    product_lines = []
    for product in products:
        meta = product.get("metadata", {}) if isinstance(product, dict) else {}
        pid = meta.get("id", "Unknown")
        desc = (product.get("content", "") if isinstance(product, dict) else str(product))[:60]
        product_lines.append(f"- **{pid}**: {desc}...")

    products_summary = "\n".join(product_lines)

    logger.info(
        "Submitted access request %s for %d product(s)", request_id, len(products),
    )

    return {
        "current_step": "done",
        "messages": [
            AIMessage(
                content=(
                    f"Your access request has been submitted successfully!\n\n"
                    f"- **Request ID:** {request_id}\n"
                    f"- **Products ({len(products)}):**\n{products_summary}\n\n"
                    f"You can check the status at any time by asking me."
                )
            )
        ],
    }
