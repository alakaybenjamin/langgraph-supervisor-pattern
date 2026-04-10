from __future__ import annotations

import logging

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from app.graph.state import AccessRequestState

logger = logging.getLogger(__name__)


def confirm_node(state: AccessRequestState) -> dict:
    products = state.get("selected_products", [])
    form_drafts = state.get("form_drafts", {})

    summary_lines = ["## Access Request Summary\n"]

    for i, product in enumerate(products):
        meta = product.get("metadata", {}) if isinstance(product, dict) else {}
        pid = meta.get("id", f"product-{i+1}")
        ptype = meta.get("product_type", "default")
        draft = form_drafts.get(pid, {})

        summary_lines.append(f"### {i+1}. {pid} [{ptype}]")
        if isinstance(draft, dict) and draft:
            for key, val in draft.items():
                summary_lines.append(f"- {key}: {val}")
        else:
            summary_lines.append("- (no form data)")
        summary_lines.append("")

    summary = "\n".join(summary_lines)

    decision = interrupt({
        "type": "confirmation",
        "message": f"{summary}\nDo you confirm and want to submit this request?",
        "actions": [
            {"id": "confirm", "label": "Submit"},
            {"id": "edit", "label": "Edit Forms"},
            {"id": "add_more", "label": "+ Add More Products"},
        ],
    })

    action = decision.get("action", "confirm") if isinstance(decision, dict) else "confirm"
    confirmed = decision.get("confirmed", action == "confirm") if isinstance(decision, dict) else bool(decision)

    if action == "edit" or not confirmed:
        logger.info("User chose to edit forms")
        return {
            "current_step": "fill_form",
            "current_product_index": 0,
            "messages": [AIMessage(content="No problem — let's go back to the forms.")],
        }

    if action == "add_more":
        logger.info("User wants to add more products")
        return {
            "current_step": "narrow",
            "selected_domain": "",
            "selected_type": "",
            "search_results": [],
            "messages": [AIMessage(content="Let's find more products to add to your request.")],
        }

    logger.info("User confirmed submission for %d product(s)", len(products))
    return {
        "current_step": "submit",
        "messages": [AIMessage(content="Submitting your request now...")],
    }
