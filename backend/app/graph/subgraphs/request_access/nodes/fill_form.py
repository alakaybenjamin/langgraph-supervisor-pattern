from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt

from app.core.config import settings
from app.graph.state import AccessRequestState

logger = logging.getLogger(__name__)

_INTENT_SYSTEM = SystemMessage(content="""\
You are an intent classifier for a data governance form-filling workflow.
The user is currently filling out an access request form for a data product.

Classify the user's message into exactly ONE of these intents:

- back_to_selection — The user wants to go back to reviewing, changing, or re-picking \
their data products. Examples: "go back to product search", "I want different products", \
"let me change my selection", "take me back to the product list".
- add_more — The user wants to add additional data products to their current request \
without changing existing ones. Examples: "I need to add another product", "forgot one more", \
"can I include another dataset".
- continue — The user wants to keep filling the form, asks about a form field, or the \
message is unrelated to navigation. This is the default if unsure.

Respond with ONLY the intent name. No explanation, no punctuation.\
""")

_classifier_llm = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=settings.OPENAI_API_KEY,
    temperature=0,
)


def _classify_form_intent(user_text: str) -> str:
    resp = _classifier_llm.invoke([_INTENT_SYSTEM, HumanMessage(content=user_text)])
    intent = resp.content.strip().lower().replace(".", "")
    if intent in ("back_to_selection", "add_more"):
        return intent
    return "continue"

MCP_RESOURCE_URI = "ui://question-form/mcp-app.html"
MCP_ENDPOINT = "/mcp/question-form"

VALID_SECTIONS = {"ddf", "default", "onyx", "productSpecific"}


def _resolve_section(product: dict) -> str:
    meta = product.get("metadata", {}) if isinstance(product, dict) else {}
    product_type = meta.get("product_type", "default")
    return product_type if product_type in VALID_SECTIONS else "default"


def fill_form_node(state: AccessRequestState) -> dict:
    products = state.get("selected_products", [])
    idx = state.get("current_product_index", 0)
    form_drafts = dict(state.get("form_drafts", {}))

    if idx >= len(products):
        return {
            "current_step": "confirm",
            "messages": [AIMessage(content="All forms completed. Let me show you a summary.")],
        }

    product = products[idx]
    meta = product.get("metadata", {}) if isinstance(product, dict) else {}
    pid = meta.get("id", f"product-{idx+1}")
    section = _resolve_section(product)
    draft = form_drafts.get(pid, {})

    logger.info(
        "fill_form: product %d/%d id=%s section=%s",
        idx + 1, len(products), pid, section,
    )

    form_data = interrupt({
        "type": "mcp_app",
        "resource_uri": MCP_RESOURCE_URI,
        "mcp_endpoint": MCP_ENDPOINT,
        "tool_name": "open-question-form",
        "tool_args": {"section": section},
        "context": {
            "selected_product": product,
            "draft_values": draft,
            "product_type": section,
            "product_index": idx,
            "total_products": len(products),
        },
    })

    action = form_data.get("action", "") if isinstance(form_data, dict) else ""

    if action == "add_more":
        logger.info("User wants to add more products (during form for %s)", pid)
        return {
            "form_drafts": form_drafts,
            "current_step": "narrow",
            "selected_domain": "",
            "selected_type": "",
            "search_results": [],
            "messages": [AIMessage(content="No problem — let's find more products to add to your request.")],
        }

    if action == "back_to_selection":
        logger.info("User wants to go back to product selection (during form for %s)", pid)
        return {
            "form_drafts": form_drafts,
            "current_step": "review_cart",
            "messages": [AIMessage(content="Sure — let's go back to your product selection.")],
        }

    if action == "user_message":
        user_text = form_data.get("text", "")
        logger.info("Free-text during form for %s: %r", pid, user_text)
        classified = _classify_form_intent(user_text)
        logger.info("Classified intent: %s", classified)

        if classified == "back_to_selection":
            return {
                "form_drafts": form_drafts,
                "current_step": "review_cart",
                "messages": [AIMessage(content="Sure — let's go back to your product selection.")],
            }
        if classified == "add_more":
            return {
                "form_drafts": form_drafts,
                "current_step": "narrow",
                "selected_domain": "",
                "selected_type": "",
                "search_results": [],
                "messages": [AIMessage(content="No problem — let's find more products to add to your request.")],
            }
        return {
            "form_drafts": form_drafts,
            "current_step": "fill_form",
            "messages": [AIMessage(
                content="The form is still open in the panel. Please complete it, "
                "or let me know if you'd like to go back to product selection or add more products."
            )],
        }

    logger.info("Form data received for %s: %d fields", pid, len(form_data) if isinstance(form_data, dict) else 0)

    form_drafts[pid] = form_data

    remaining = len(products) - idx - 1
    if remaining > 0:
        msg = f"Form for **{pid}** saved. {remaining} more product(s) to go."
    else:
        msg = f"Form for **{pid}** saved. All products done — let me show you the summary."

    return {
        "form_drafts": form_drafts,
        "current_product_index": idx + 1,
        "current_step": "fill_form" if remaining > 0 else "confirm",
        "messages": [AIMessage(content=msg)],
    }
