from __future__ import annotations

"""Business step nodes for the request-access subgraph.

Each HITL step:

1. Builds a structured interrupt payload (chips, cards, form, confirmation).
2. Calls ``interrupt(payload)`` to pause the graph.
3. On resume, stashes the resume value into ``state.last_resume_value`` and
   routes back to ``route_request_access_turn`` which performs classification
   and dispatch (answer / nav / faq / user_text).

Internal pure steps (``search_products``, ``generate_dynamic_form``) do not
interrupt; they just transform state and hand off to the next node.
"""

import logging
import uuid

from langchain_core.messages import AIMessage
from langgraph.types import Command, interrupt

from app.graph.state import (
    RA_STEP_CHOOSE_ANONYMIZATION,
    RA_STEP_CHOOSE_DOMAIN,
    RA_STEP_CHOOSE_PRODUCTS,
    RA_STEP_FILL_FORM,
    RA_STEP_GENERATE_FORM,
    RA_STEP_SEARCH_PRODUCTS,
    RA_STEP_SHOW_CART,
    RA_STEP_SUBMIT,
    AppState,
)
from app.graph.subgraphs.request_access.helpers import (
    CART_ACTIONS,
    CART_ACTIONS_READONLY,
    QUESTION_FORM_PAYLOAD,
    build_emit_ui_payload,
    build_search_products_query,
    merge_form_schema_for_products,
    normalize_products,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HITL step template
# ---------------------------------------------------------------------------


def _hitl_step(
    *,
    state: AppState,
    node_name: str,
    step_id: str,
    payload: dict,
) -> Command:
    """Shared scaffolding: mark step active, interrupt, then route back."""
    # Make the pre-interrupt state available to supervisor_router on re-entry.
    # NB: any pre-interrupt state updates returned here will not persist until
    # the node completes — so the post-resume return is the source of truth.
    logger.info("%s: pausing on interrupt (step=%s)", node_name, step_id)
    value = interrupt(payload)
    logger.info("%s: resumed with %r", node_name, value)
    return Command(
        update={
            "last_resume_value": value,
            "last_workflow_node": node_name,
            "current_step": step_id,
            "awaiting_input": False,
            "pending_prompt": None,
            "paused_workflow_summary": _summary_for(state, step_id),
            "active_flow": "request_access",
            "mode": "workflow",
        },
        goto="route_request_access_turn",
    )


def _summary_for(state: AppState, step: str) -> str:
    domain = (state.get("selected_domains") or ["?"])[0]
    anon = state.get("selected_anonymization") or "?"
    prod_count = len(state.get("selected_products") or [])
    return f"step={step}, domain={domain}, anon={anon}, selected_products={prod_count}"


# ---------------------------------------------------------------------------
# Step nodes
# ---------------------------------------------------------------------------


def choose_domain(state: AppState) -> Command:
    payload = build_emit_ui_payload(
        ui_type="facet_selection",
        message="Choose the **data domain** for your access request.",
        facet="domain",
        step=RA_STEP_CHOOSE_DOMAIN,
    )
    return _hitl_step(
        state=state,
        node_name="choose_domain",
        step_id=RA_STEP_CHOOSE_DOMAIN,
        payload=payload,
    )


def choose_anonymization(state: AppState) -> Command:
    payload = build_emit_ui_payload(
        ui_type="facet_selection",
        message="Choose the **anonymization / data handling** level you need.",
        facet="anonymization",
        step=RA_STEP_CHOOSE_ANONYMIZATION,
    )
    return _hitl_step(
        state=state,
        node_name="choose_anonymization",
        step_id=RA_STEP_CHOOSE_ANONYMIZATION,
        payload=payload,
    )


def search_products(state: AppState) -> Command:
    """Pure (non-HITL) step: runs the vector search and advances state."""
    domains = state.get("selected_domains") or ["all"]
    domain = domains[0] if domains else "all"
    ptype = state.get("product_type_filter") or "all"
    query = (state.get("ra_search_query") or "").strip() or "data product"
    results = build_search_products_query(
        query=query, domain=domain, product_type=ptype, k=8,
    )
    return Command(
        update={
            "product_search_results": results,
            "current_step": RA_STEP_CHOOSE_PRODUCTS,
            "last_workflow_node": "search_products",
        },
        goto="choose_products",
    )


def choose_products(state: AppState) -> Command:
    products = normalize_products(state.get("product_search_results") or [])
    payload = build_emit_ui_payload(
        ui_type="product_selection",
        message="Select one or more **data products** to include.",
        products=products,
        step=RA_STEP_CHOOSE_PRODUCTS,
    )
    return _hitl_step(
        state=state,
        node_name="choose_products",
        step_id=RA_STEP_CHOOSE_PRODUCTS,
        payload=payload,
    )


def show_cart(state: AppState) -> Command:
    products = normalize_products(state.get("selected_products") or [])
    payload = build_emit_ui_payload(
        ui_type="cart_review",
        message="Review your **selected products** before generating access forms.",
        products=products,
        actions=CART_ACTIONS,
        step=RA_STEP_SHOW_CART,
    )
    return _hitl_step(
        state=state,
        node_name="show_cart",
        step_id=RA_STEP_SHOW_CART,
        payload=payload,
    )


def show_cart_readonly(state: AppState) -> Command:
    products = normalize_products(
        state.get("selected_products") or state.get("cart_snapshot") or []
    )
    payload = build_emit_ui_payload(
        ui_type="cart_review",
        message="**Your current selection** (read-only). Continue the workflow when ready.",
        products=products,
        actions=CART_ACTIONS_READONLY,
        step=RA_STEP_SHOW_CART,
    )
    return _hitl_step(
        state=state,
        node_name="show_cart_readonly",
        step_id=state.get("current_step") or RA_STEP_SHOW_CART,
        payload=payload,
    )


def generate_dynamic_form(state: AppState) -> Command:
    products = normalize_products(state.get("selected_products") or [])
    schema = merge_form_schema_for_products(products)
    return Command(
        update={
            "generated_form_schema": schema,
            "current_step": RA_STEP_FILL_FORM,
            "last_workflow_node": "generate_dynamic_form",
        },
        goto="fill_form",
    )


def fill_form(state: AppState) -> Command:
    payload = dict(QUESTION_FORM_PAYLOAD)
    payload["step"] = RA_STEP_FILL_FORM
    payload["prompt_id"] = str(uuid.uuid4())
    payload["context"] = {
        "products": normalize_products(state.get("selected_products") or []),
        "schema": state.get("generated_form_schema") or [],
    }
    return _hitl_step(
        state=state,
        node_name="fill_form",
        step_id=RA_STEP_FILL_FORM,
        payload=payload,
    )


def submit_request(state: AppState) -> Command | dict:
    """Final confirmation + submission.

    If ``submit_confirmed`` is already True (set by the router after a
    confirm click), finalize the request. Otherwise, show a confirmation
    interrupt and wait.
    """
    if state.get("submit_confirmed"):
        rid = state.get("last_request_id") or f"REQ-{uuid.uuid4().hex[:6].upper()}"
        logger.info("submit_request: finalized %s", rid)
        return {
            "messages": [
                AIMessage(
                    content=(
                        f"Your access request **{rid}** has been submitted successfully. "
                        "You'll receive a confirmation email shortly."
                    )
                )
            ],
            "last_request_id": rid,
            "submit_confirmed": False,
            "active_flow": "none",
            "mode": "idle",
            "pending_prompt": None,
            "awaiting_input": False,
            "current_step": "",
            "last_workflow_node": "submit_request",
        }

    products = normalize_products(state.get("selected_products") or [])
    form_data = state.get("form_answers") or {}
    lines = [f"- **{(p.get('metadata') or {}).get('id', '?')}**" for p in products]
    payload = {
        "type": "confirmation",
        "message": "Review and confirm your access request submission.",
        "products": products,
        "form_data": form_data,
        "products_summary": "\n".join(lines) if lines else "(no products)",
        "step": RA_STEP_SUBMIT,
        "prompt_id": str(uuid.uuid4()),
        "actions": [
            {"id": "submit", "label": "Submit Request"},
            {"id": "edit", "label": "Edit"},
            {"id": "cancel", "label": "Cancel"},
        ],
    }
    return _hitl_step(
        state=state,
        node_name="submit_request",
        step_id=RA_STEP_SUBMIT,
        payload=payload,
    )
