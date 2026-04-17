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
    facet_options_from_cache,
    merge_form_schema_for_products,
    normalize_products,
)
from app.graph.subgraphs.request_access.prompts import (
    CHOOSE_ANONYMIZATION_MESSAGE,
    CHOOSE_DOMAIN_MESSAGE,
    CHOOSE_PRODUCTS_MESSAGE,
    SHOW_CART_MESSAGE,
    SHOW_CART_READONLY_MESSAGE,
    SUBMIT_CONFIRMATION_ACTIONS,
    SUBMIT_CONFIRMATION_MESSAGE,
    SUBMIT_PRODUCTS_EMPTY,
    SUBMIT_SUCCESS_TEMPLATE,
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


_STEP_LABELS: dict[str, str] = {
    RA_STEP_CHOOSE_DOMAIN: "choosing the data domain",
    RA_STEP_CHOOSE_ANONYMIZATION: "choosing the anonymization level",
    RA_STEP_SEARCH_PRODUCTS: "searching for products",
    RA_STEP_CHOOSE_PRODUCTS: "picking products",
    RA_STEP_SHOW_CART: "reviewing your cart",
    RA_STEP_GENERATE_FORM: "preparing your access form",
    RA_STEP_FILL_FORM: "filling out the access form",
    RA_STEP_SUBMIT: "confirming your submission",
}

_ANON_LABELS: dict[str, str] = {
    "deidentified": "de-identified",
    "de-identified": "de-identified",
    "anonymized": "anonymized",
    "identified": "identified",
    "raw": "raw",
}


def _summary_for(state: AppState, step: str) -> str:
    """Build a short, human-friendly sentence fragment describing where the
    user is in the request-access workflow. Consumed as-is by the FAQ suffix
    template (user-visible) and by ``_workflow_summary`` fallbacks.
    """
    pretty_step = _STEP_LABELS.get(step, step.replace("_", " "))
    domains = [d for d in (state.get("selected_domains") or []) if d and d != "all"]
    anon_raw = state.get("selected_anonymization") or ""
    anon = _ANON_LABELS.get(anon_raw, anon_raw)
    prod_count = len(state.get("selected_products") or [])

    parts = [f"on the **{pretty_step}** step"]
    if prod_count:
        parts.append(
            f"with {prod_count} product{'s' if prod_count != 1 else ''} selected"
        )
    extras: list[str] = []
    if domains:
        extras.append(f"domain: {', '.join(domains)}")
    if anon:
        extras.append(f"anonymization: {anon}")
    if extras:
        parts.append(f"({'; '.join(extras)})")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Step nodes
# ---------------------------------------------------------------------------


def choose_domain(state: AppState) -> Command:
    payload = build_emit_ui_payload(
        ui_type="facet_selection",
        message=CHOOSE_DOMAIN_MESSAGE,
        facet="domain",
        options=facet_options_from_cache(state, "domain"),
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
        message=CHOOSE_ANONYMIZATION_MESSAGE,
        facet="anonymization",
        options=facet_options_from_cache(state, "anonymization"),
        step=RA_STEP_CHOOSE_ANONYMIZATION,
    )
    return _hitl_step(
        state=state,
        node_name="choose_anonymization",
        step_id=RA_STEP_CHOOSE_ANONYMIZATION,
        payload=payload,
    )


async def search_products(state: AppState) -> Command:
    """Pure (non-HITL) step: calls the MCP ``search`` tool and advances state.

    Async because the MCP client speaks streamable HTTP; LangGraph invokes
    async nodes natively via ``astream`` / ``ainvoke`` (which the chat SSE
    handler already uses).
    """
    domains = state.get("selected_domains") or []
    anonymization = state.get("selected_anonymization") or None
    study_id = state.get("ra_study_id") or None
    query = (state.get("ra_search_query") or "").strip() or "*"
    results = await build_search_products_query(
        query=query,
        domains=list(domains) if domains else None,
        anonymization=anonymization,
        study_id=study_id,
        k=8,
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
        message=CHOOSE_PRODUCTS_MESSAGE,
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
        message=SHOW_CART_MESSAGE,
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
        message=SHOW_CART_READONLY_MESSAGE,
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
                    content=SUBMIT_SUCCESS_TEMPLATE.format(request_id=rid)
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
        "message": SUBMIT_CONFIRMATION_MESSAGE,
        "products": products,
        "form_data": form_data,
        "products_summary": "\n".join(lines) if lines else SUBMIT_PRODUCTS_EMPTY,
        "step": RA_STEP_SUBMIT,
        "prompt_id": str(uuid.uuid4()),
        "actions": list(SUBMIT_CONFIRMATION_ACTIONS),
    }
    return _hitl_step(
        state=state,
        node_name="submit_request",
        step_id=RA_STEP_SUBMIT,
        payload=payload,
    )
