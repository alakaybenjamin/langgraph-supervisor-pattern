from __future__ import annotations

import logging

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from app.graph.state import AccessRequestState

logger = logging.getLogger(__name__)

DOMAIN_OPTIONS = [
    {"id": "r_and_d", "label": "R&D / Clinical"},
    {"id": "commercial", "label": "Commercial"},
    {"id": "safety", "label": "Safety"},
    {"id": "operations", "label": "Operations"},
    {"id": "finance", "label": "Finance"},
    {"id": "hr", "label": "HR"},
    {"id": "it", "label": "IT"},
    {"id": "regulatory", "label": "Regulatory"},
    {"id": "all", "label": "All Domains"},
]

TYPE_OPTIONS = [
    {"id": "ddf", "label": "DDF"},
    {"id": "default", "label": "Default"},
    {"id": "onyx", "label": "Onyx"},
    {"id": "all", "label": "Any Type"},
]


def narrow_node(state: AccessRequestState) -> dict:
    domain = state.get("selected_domain", "")
    product_type = state.get("selected_type", "")

    if not domain:
        choice = interrupt({
            "type": "facet_selection",
            "facet": "domain",
            "message": "What domain are you interested in?",
            "options": DOMAIN_OPTIONS,
        })
        selected_domain = choice.get("value", "all") if isinstance(choice, dict) else str(choice)
        logger.info("User selected domain: %s", selected_domain)
        return {
            "selected_domain": selected_domain,
            "messages": [AIMessage(content=f"Domain: **{selected_domain}**. Now, what type of data product?")],
        }

    if not product_type:
        choice = interrupt({
            "type": "facet_selection",
            "facet": "product_type",
            "message": "What type of data product are you looking for?",
            "options": TYPE_OPTIONS,
        })
        selected_type = choice.get("value", "all") if isinstance(choice, dict) else str(choice)
        logger.info("User selected type: %s", selected_type)
        return {
            "selected_type": selected_type,
            "messages": [AIMessage(content=f"Type: **{selected_type}**. Searching for matching products...")],
        }

    return {
        "messages": [AIMessage(content="Filters already set, proceeding to results.")],
    }
