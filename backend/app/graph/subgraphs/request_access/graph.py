from __future__ import annotations

"""Compiled request-access subgraph.

Pattern: this subgraph is a compiled ``StateGraph`` attached as a single node
to the parent supervisor graph. It owns its own intra-flow router
(``route_request_access_turn``) and defers inter-flow handoffs to the parent
via ``Command(graph=Command.PARENT, goto=…)``.

Checkpointing is set on the parent graph only — it propagates to this
subgraph automatically because the subgraph is a compiled node, not a
separately-invoked graph.
"""

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graph.router_logic import classify_resume_value
from app.graph.state import (
    RA_STEP_CHOOSE_ANONYMIZATION,
    RA_STEP_CHOOSE_DOMAIN,
    RA_STEP_CHOOSE_PRODUCTS,
    RA_STEP_FILL_FORM,
    RA_STEP_GENERATE_FORM,
    RA_STEP_SEARCH_PRODUCTS,
    RA_STEP_SHOW_CART,
    RA_STEP_SUBMIT,
    RA_STEP_TO_NODE,
    AppState,
)
from app.graph.subgraphs.request_access.helpers import SEARCH_APP_PAYLOAD
from app.graph.subgraphs.request_access.nodes.navigation import (
    goto_target_step,
    handle_navigation,
    invalidate_downstream_state,
)
from app.graph.subgraphs.request_access.nodes.steps import (
    choose_anonymization,
    choose_domain,
    choose_products,
    fill_form,
    generate_dynamic_form,
    search_products,
    show_cart,
    show_cart_readonly,
    submit_request,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intra-flow router
# ---------------------------------------------------------------------------


def _dispatch_fresh(state: AppState) -> str:
    """Return the next step node to run when no resume value is present."""
    cs = state.get("current_step") or ""
    if cs in RA_STEP_TO_NODE:
        return RA_STEP_TO_NODE[cs]
    # Infer from state when starting fresh
    if not state.get("selected_domains"):
        return "choose_domain"
    if not state.get("selected_anonymization"):
        return "choose_anonymization"
    if not state.get("product_search_results"):
        return "search_products"
    if not state.get("selected_products"):
        return "choose_products"
    if not state.get("generated_form_schema"):
        return "show_cart"
    if not state.get("form_answers"):
        return "generate_dynamic_form"
    return "fill_form"


def _apply_structured_answer(
    state: AppState, value: dict, pending_step: str
) -> dict:
    """Merge a structured answer payload into state updates.

    Returns a dict with one or more of:
      - ``update``: state patch
      - ``next_node``: node name to goto
      - ``open_mcp_search``: True if the user requested the Search MCP panel
    """
    # --- Facet chip answers ---
    if "facet" in value and "value" in value:
        facet = str(value["facet"])
        v = str(value["value"])
        upd: dict = {
            "pending_prompt": None,
            "awaiting_input": False,
            "last_resume_value": None,
        }
        if facet == "domain":
            upd["selected_domains"] = [v]
            upd["current_step"] = RA_STEP_CHOOSE_ANONYMIZATION
            return {"update": upd, "next_node": "choose_anonymization"}
        if facet == "anonymization":
            upd["selected_anonymization"] = v
            upd["current_step"] = RA_STEP_SEARCH_PRODUCTS
            return {"update": upd, "next_node": "search_products"}
        if facet == "product_type":
            upd["product_type_filter"] = v
            upd["current_step"] = RA_STEP_SEARCH_PRODUCTS
            return {"update": upd, "next_node": "search_products"}

    # --- Product multi-select answer ---
    if value.get("action") == "select" and "products" in value:
        prods = value.get("products") or []
        return {
            "update": {
                "selected_products": prods,
                "cart_snapshot": prods,
                "pending_prompt": None,
                "awaiting_input": False,
                "last_resume_value": None,
                "current_step": RA_STEP_SHOW_CART,
            },
            "next_node": "show_cart",
        }

    # --- Product-selection UX escape hatches ---
    if value.get("action") == "open_search":
        return {"open_mcp_search": True}
    if value.get("action") == "refine_filters":
        return {
            "update": {
                "pending_prompt": None,
                "awaiting_input": False,
                "last_resume_value": None,
                "nav_intent": RA_STEP_CHOOSE_DOMAIN,
            },
            "next_node": "handle_navigation",
        }

    # --- Cart actions ---
    if value.get("action") == "fill_forms":
        return {
            "update": {
                "pending_prompt": None,
                "awaiting_input": False,
                "last_resume_value": None,
                "current_step": RA_STEP_GENERATE_FORM,
            },
            "next_node": "generate_dynamic_form",
        }

    # --- MCP search panel results ---
    if "selected_products" in value:
        prods = value.get("selected_products") or []
        return {
            "update": {
                "selected_products": prods,
                "cart_snapshot": prods,
                "pending_prompt": None,
                "awaiting_input": False,
                "last_resume_value": None,
                "current_step": RA_STEP_SHOW_CART,
            },
            "next_node": "show_cart",
        }
    if value.get("cancelled") is True:
        return {
            "update": {
                "pending_prompt": None,
                "awaiting_input": False,
                "last_resume_value": None,
                "nav_intent": RA_STEP_CHOOSE_DOMAIN,
            },
            "next_node": "handle_navigation",
        }

    # --- Form submission ---
    if isinstance(value.get("form_data"), dict) or isinstance(value.get("answers"), dict):
        form = value.get("form_data") or value.get("answers") or {}
        return {
            "update": {
                "form_answers": form if isinstance(form, dict) else {},
                "pending_prompt": None,
                "awaiting_input": False,
                "last_resume_value": None,
                "current_step": RA_STEP_SUBMIT,
            },
            "next_node": "submit_request",
        }

    # --- Final confirmation dialog ---
    action = value.get("action")
    if action in ("submit", "confirm") or value.get("confirmed") is True:
        return {
            "update": {
                "pending_prompt": None,
                "awaiting_input": False,
                "last_resume_value": None,
                "submit_confirmed": True,
            },
            "next_node": "submit_request",
        }
    if action in ("edit", "cancel") or value.get("confirmed") is False:
        return {
            "update": {
                "pending_prompt": None,
                "awaiting_input": False,
                "last_resume_value": None,
                "current_step": RA_STEP_FILL_FORM,
            },
            "next_node": "fill_form",
        }

    return {}


def _workflow_summary(state: AppState) -> str:
    parts: list[str] = []
    if cs := state.get("current_step"):
        parts.append(f"current_step={cs}")
    if sd := state.get("selected_domains"):
        parts.append(f"selected_domain={sd[0]}")
    if sa := state.get("selected_anonymization"):
        parts.append(f"selected_anonymization={sa}")
    if sp := state.get("selected_products"):
        parts.append(f"selected_products_count={len(sp)}")
    return ", ".join(parts)


def route_request_access_turn(state: AppState) -> Command | dict:
    """Intra-flow router for the request-access subgraph.

    Decides: handle_navigation, run_current_workflow_step, step dispatch,
    or handoff_to_parent_faq. All free-text classification is delegated to
    :func:`classify_resume_value` which calls gpt-4o under the hood.
    """
    value = state.get("last_resume_value")

    # -- Parent-set nav intent takes priority (supervisor LLM already decided).
    if value is None and state.get("nav_intent"):
        logger.info(
            "route_request_access_turn: parent nav_intent=%s", state.get("nav_intent")
        )
        return Command(
            update={"last_workflow_node": "route_request_access_turn"},
            goto="handle_navigation",
        )

    # -- Fresh turn (no pending resume value). Dispatch to the current step. --
    if value is None:
        logger.info("route_request_access_turn: fresh -> run_current_workflow_step")
        return Command(
            update={
                "active_flow": "request_access",
                "mode": "workflow",
                "last_workflow_node": "route_request_access_turn",
            },
            goto="run_current_workflow_step",
        )

    # -- Classify the resume value (LLM-backed for free text) -----------------
    result = classify_resume_value(value, workflow_summary=_workflow_summary(state))
    kind = result.get("kind")
    raw = result.get("raw_response")
    extra_messages = [raw] if raw is not None else []
    logger.info("route_request_access_turn: resume kind=%s", kind)

    if kind == "faq" or kind == "general_web":
        # Hand off to the parent directly so the classifier's AIMessage (which
        # carries the user's current question in its tool_call args) reaches
        # parent state in the SAME ``Command.PARENT`` update. A two-step
        # handoff via an intermediate subgraph node would lose this message:
        # subgraph-local ``messages`` updates do not propagate to parent when
        # a later node exits via ``Command(graph=Command.PARENT, ...)``.
        target = "faq_kb_agent" if kind == "faq" else "general_faq_tavily_agent"
        return _handoff_to_parent_faq(state, goto=target, extra_messages=extra_messages)

    if kind == "nav":
        intent = result.get("nav_target") or RA_STEP_CHOOSE_DOMAIN
        return Command(
            update={
                "nav_intent": intent,
                "last_resume_value": None,
                "last_workflow_node": "route_request_access_turn",
                **({"messages": extra_messages} if extra_messages else {}),
            },
            goto="handle_navigation",
        )

    if kind == "answer" and isinstance(value, dict):
        merged = _apply_structured_answer(
            state, value, pending_step=state.get("current_step") or ""
        )
        if merged.get("open_mcp_search"):
            payload = dict(SEARCH_APP_PAYLOAD)
            payload["context"] = {
                "filters": {
                    "domain": (state.get("selected_domains") or ["all"])[0],
                    "product_type": state.get("product_type_filter") or "all",
                }
            }
            payload["step"] = RA_STEP_CHOOSE_PRODUCTS
            payload["prompt_id"] = "mcp_search"
            return Command(
                update={
                    "pending_prompt": payload,
                    "awaiting_input": True,
                    "last_resume_value": None,
                    "current_step": RA_STEP_CHOOSE_PRODUCTS,
                },
                goto="choose_products",
            )
        if merged:
            return Command(
                update=merged.get("update", {}),
                goto=merged.get("next_node", END),
            )
        logger.warning("route_request_access_turn: unmatched answer payload %r", value)

    if kind == "resume":
        # User said "continue" / "keep going" — advance to the current step.
        target = RA_STEP_TO_NODE.get(state.get("current_step") or "", "choose_domain")
        return Command(
            update={
                "last_resume_value": None,
                **({"messages": extra_messages} if extra_messages else {}),
            },
            goto=target,
        )

    if kind == "user_text":
        # Side-comment / chit-chat — append a gentle reminder and re-enter the
        # current step so its interrupt payload is redisplayed.
        target = RA_STEP_TO_NODE.get(state.get("current_step") or "", "choose_domain")
        side_note = AIMessage(
            content=(
                "I'm waiting for your selection in the panel above. "
                "You can also ask a **process or policy question** — your "
                "access request stays paused."
            )
        )
        return Command(
            update={
                "messages": extra_messages + [side_note],
                "last_resume_value": None,
            },
            goto=target,
        )

    logger.warning("route_request_access_turn: unhandled resume value %r", value)
    target = RA_STEP_TO_NODE.get(state.get("current_step") or "", "choose_domain")
    return Command(update={"last_resume_value": None}, goto=target)


# ---------------------------------------------------------------------------
# Branch nodes for the four semantic destinations from the router
# ---------------------------------------------------------------------------


def resume_pending_step(state: AppState) -> Command:
    """Explicit label for the 'answer' branch. Re-dispatches by current_step."""
    target = RA_STEP_TO_NODE.get(state.get("current_step") or "", "choose_domain")
    logger.info("resume_pending_step: -> %s", target)
    return Command(goto=target)


def run_current_workflow_step(state: AppState) -> Command:
    """Dispatches based on persisted ``current_step`` (or inferred state)."""
    target = _dispatch_fresh(state)
    logger.info("run_current_workflow_step: -> %s", target)
    return Command(goto=target)


def _handoff_to_parent_faq(
    state: AppState,
    *,
    goto: str = "faq_kb_agent",
    extra_messages: list[Any] | None = None,
) -> Command:
    """Hand control back to the parent supervisor's FAQ agent.

    Uses ``Command(graph=Command.PARENT, goto=…)`` so the subgraph exits and
    the parent graph runs the target FAQ agent. Because compiled subgraphs
    have their own state container, any subgraph-local state updates made in
    *earlier* subgraph nodes during this turn do NOT automatically propagate
    to parent state when a later node exits via ``Command.PARENT``. That
    means:

    * The classifier's ``AIMessage`` (with the ``ask_faq_kb`` tool-call whose
      ``question`` argument is the user's current message) must be included
      in this PARENT update's ``messages`` field, or the parent
      ``faq_kb_agent`` will never see it and will fall back to a stale
      ``HumanMessage``.
    * The workflow-state fields we want the parent (and next turn's
      ``supervisor_router``) to see must all be lifted explicitly.
    """
    summary = state.get("paused_workflow_summary") or (
        f"current_step={state.get('current_step') or '?'}"
    )
    logger.info("handoff_to_parent_faq: summary=%s goto=%s", summary, goto)
    update: dict = {
        "active_flow": "request_access",
        "mode": "faq",
        "active_intent": "faq" if goto == "faq_kb_agent" else "general_faq",
        "faq_context": {"from_workflow": True, "summary": summary},
        "paused_workflow_summary": summary,
        "current_step": state.get("current_step") or "",
        "awaiting_input": True,
        "pending_prompt": state.get("pending_prompt"),
        "selected_domains": state.get("selected_domains") or [],
        "selected_anonymization": state.get("selected_anonymization"),
        "product_type_filter": state.get("product_type_filter") or "all",
        "product_search_results": state.get("product_search_results") or [],
        "selected_products": state.get("selected_products") or [],
        "cart_snapshot": state.get("cart_snapshot") or [],
        "generated_form_schema": state.get("generated_form_schema") or [],
        "form_answers": state.get("form_answers") or {},
        "last_resume_value": None,
    }
    if extra_messages:
        update["messages"] = list(extra_messages)
    return Command(graph=Command.PARENT, update=update, goto=goto)


def handoff_to_parent_faq(state: AppState) -> Command:
    """Legacy node entry point — retained for safety if any path still routes
    here directly. New flows should call ``_handoff_to_parent_faq`` from the
    router so the classifier AIMessage is included in the PARENT update.
    """
    return _handoff_to_parent_faq(state)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_request_access_subgraph() -> Any:
    builder = StateGraph(AppState)

    # Router + semantic branches
    builder.add_node("route_request_access_turn", route_request_access_turn)
    builder.add_node("resume_pending_step", resume_pending_step)
    builder.add_node("run_current_workflow_step", run_current_workflow_step)
    builder.add_node("handoff_to_parent_faq", handoff_to_parent_faq)

    # Navigation
    builder.add_node("handle_navigation", handle_navigation)
    builder.add_node("invalidate_downstream_state", invalidate_downstream_state)
    builder.add_node("goto_target_step", goto_target_step)

    # Business steps
    builder.add_node("choose_domain", choose_domain)
    builder.add_node("choose_anonymization", choose_anonymization)
    builder.add_node("search_products", search_products)
    builder.add_node("choose_products", choose_products)
    builder.add_node("show_cart", show_cart)
    builder.add_node("show_cart_readonly", show_cart_readonly)
    builder.add_node("generate_dynamic_form", generate_dynamic_form)
    builder.add_node("fill_form", fill_form)
    builder.add_node("submit_request", submit_request)

    builder.add_edge(START, "route_request_access_turn")

    # Terminal edges: any step that returns without a Command(goto=…) ends the
    # subgraph turn. Since every node above returns Command, we only wire
    # fall-through edges for safety.
    for n in (
        "resume_pending_step",
        "run_current_workflow_step",
        "handoff_to_parent_faq",
        "handle_navigation",
        "invalidate_downstream_state",
        "goto_target_step",
        "choose_domain",
        "choose_anonymization",
        "search_products",
        "choose_products",
        "show_cart",
        "show_cart_readonly",
        "generate_dynamic_form",
        "fill_form",
        "submit_request",
    ):
        builder.add_edge(n, END)

    return builder.compile()
