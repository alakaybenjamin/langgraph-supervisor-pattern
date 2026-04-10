from __future__ import annotations

import logging

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from app.graph.state import AccessRequestState

logger = logging.getLogger(__name__)


def review_cart_node(state: AccessRequestState) -> dict:
    products = state.get("selected_products", [])

    if not products:
        return {
            "current_step": "narrow",
            "selected_domain": "",
            "selected_type": "",
            "messages": [AIMessage(content="No products selected. Let's search again.")],
        }

    product_lines = []
    for i, p in enumerate(products):
        meta = p.get("metadata", {}) if isinstance(p, dict) else {}
        pid = meta.get("id", f"product-{i+1}")
        ptype = meta.get("product_type", "default")
        desc = (p.get("content", "") if isinstance(p, dict) else str(p))[:60]
        product_lines.append(f"{i+1}. **{pid}** [{ptype}] — {desc}...")

    summary = "\n".join(product_lines)

    response = interrupt({
        "type": "cart_review",
        "message": (
            f"You've selected {len(products)} data product(s):\n\n"
            f"{summary}\n\n"
            "What would you like to do?"
        ),
        "products": products,
        "actions": [
            {"id": "fill_forms", "label": "Fill Access Forms"},
            {"id": "add_more", "label": "+ Add More Products"},
            {"id": "change_selection", "label": "Change Selection"},
        ],
    })

    action = response.get("action", "fill_forms") if isinstance(response, dict) else "fill_forms"

    if action == "add_more":
        return {
            "current_step": "narrow",
            "selected_domain": "",
            "selected_type": "",
            "search_results": [],
            "messages": [AIMessage(content="Let's find more products to add to your request.")],
        }

    if action == "change_selection":
        return {
            "selected_products": [],
            "current_step": "narrow",
            "selected_domain": "",
            "selected_type": "",
            "search_results": [],
            "messages": [AIMessage(content="Selection cleared. Let's start the search again.")],
        }

    return {
        "current_step": "fill_form",
        "current_product_index": 0,
        "messages": [AIMessage(content="Let's fill out the access request forms for your selected products.")],
    }
