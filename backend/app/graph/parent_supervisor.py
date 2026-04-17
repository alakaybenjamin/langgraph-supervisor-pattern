from __future__ import annotations

"""Parent supervisor / router graph-level nodes.

- :func:`recover_state_node` — initializes defaults for missing workflow
  fields so routing never sees ``None``.
- :func:`supervisor_router` — the top-level router. Picks which sibling
  component handles the current turn: request-access subgraph,
  ``faq_kb_agent``, ``general_faq_tavily_agent``, or ``status_agent``.

Routing strategy
----------------

All free-text intent classification is performed by a gpt-4o tool-calling
LLM (see :mod:`app.graph.router_logic`). Structured UI payloads from button
clicks are dispatched deterministically — they're a typed contract with
the frontend, not something to infer.

Decision tree:

1. **Structured UI resume** (``additional_kwargs['ra_ui']`` present) — always
   goes straight to ``request_access_subgraph``.
2. **Active paused workflow** (``active_flow == "request_access"``) — uses
   :func:`classify_workflow_text` (gpt-4o) to decide between:
   - ``faq``        → ``faq_kb_agent``
   - ``general_web``→ ``general_faq_tavily_agent``
   - ``nav``        → subgraph, with ``nav_intent`` set
   - ``resume`` / ``side_text`` → subgraph, which redisplays the pending step
3. **Fresh turn** (no active workflow) — uses
   :func:`classify_fresh_turn_text` (gpt-4o) to decide between:
   - ``start_access`` → subgraph
   - ``faq_kb``       → ``faq_kb_agent``
   - ``general_web``  → ``general_faq_tavily_agent``
   - ``status_check`` → ``status_agent``
   - ``direct``       → reply directly (rare; only when intent is unclear)
"""

import logging
from typing import Literal

from langgraph.types import Command

from app.graph.router_logic import (
    classify_fresh_turn_text,
    classify_workflow_text,
    last_human_message,
)
from app.graph.state import AppState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# recover_state
# ---------------------------------------------------------------------------


_STATE_DEFAULTS: dict = {
    "active_flow": "none",
    "mode": "idle",
    "active_intent": "",
    "supervisor_decision": "",
    "faq_context": {},
    "paused_workflow_summary": "",
    "current_step": "",
    "awaiting_input": False,
    "pending_prompt": None,
    "selected_domains": [],
    "selected_anonymization": None,
    "product_type_filter": "all",
    "product_search_results": [],
    "selected_products": [],
    "cart_snapshot": [],
    "generated_form_schema": [],
    "form_answers": {},
    "last_workflow_node": "",
    "nav_intent": None,
    "invalidated_from_step": None,
    "last_resume_value": None,
    "ra_search_query": "",
    "submit_confirmed": False,
    "last_request_id": "",
}


def recover_state_node(state: AppState) -> dict:
    patch: dict = {}
    for key, default in _STATE_DEFAULTS.items():
        if state.get(key) is None:
            patch[key] = default
    if patch:
        logger.debug("recover_state: defaulting %d keys", len(patch))
    return patch


# ---------------------------------------------------------------------------
# supervisor_router
# ---------------------------------------------------------------------------


_SupervisorTarget = Literal[
    "request_access_subgraph",
    "faq_kb_agent",
    "general_faq_tavily_agent",
    "status_agent",
    "__end__",
]


def _dispatch(target: _SupervisorTarget, **update) -> Command:
    update.setdefault("supervisor_decision", target)
    return Command(update=update, goto=target)


def _workflow_summary(state: AppState) -> str:
    parts: list[str] = []
    if cs := state.get("current_step"):
        parts.append(f"current_step={cs}")
    if (sd := state.get("selected_domains")):
        parts.append(f"selected_domain={sd[0]}")
    if (sa := state.get("selected_anonymization")):
        parts.append(f"selected_anonymization={sa}")
    if sp := state.get("selected_products"):
        parts.append(f"selected_products_count={len(sp)}")
    if not parts:
        return ""
    return ", ".join(parts)


def supervisor_router(state: AppState) -> Command[_SupervisorTarget] | dict:
    msg, text, kwargs = last_human_message(state)
    text = (text or "").strip()

    # ---- 1) Structured UI resume — always subgraph --------------------------
    if kwargs.get("ra_ui") is not None:
        logger.info("supervisor_router: structured ra_ui -> request_access_subgraph")
        return _dispatch(
            "request_access_subgraph",
            active_intent="request_access",
            active_flow="request_access",
            mode="workflow",
        )

    # ---- 2) Active paused workflow — LLM classifier inside-workflow context -
    if state.get("active_flow") == "request_access":
        if not text:
            logger.info("supervisor_router: active RA, no new text -> subgraph")
            return _dispatch(
                "request_access_subgraph",
                active_intent="request_access",
                mode="workflow",
            )

        result = classify_workflow_text(text, workflow_summary=_workflow_summary(state))
        kind = result.get("kind")
        raw = result.get("raw_response")
        msgs_update = [raw] if raw is not None else []

        if kind == "faq":
            logger.info("supervisor_router: in-workflow FAQ -> faq_kb_agent")
            return _dispatch(
                "faq_kb_agent",
                mode="faq",
                active_intent="faq",
                **({"messages": msgs_update} if msgs_update else {}),
            )
        if kind == "general_web":
            logger.info("supervisor_router: in-workflow general -> tavily")
            return _dispatch(
                "general_faq_tavily_agent",
                mode="faq",
                active_intent="general_faq",
                **({"messages": msgs_update} if msgs_update else {}),
            )
        if kind == "nav":
            target = result.get("nav_target") or "choose_domain"
            logger.info("supervisor_router: in-workflow nav target=%s", target)
            return _dispatch(
                "request_access_subgraph",
                active_intent="request_access",
                mode="workflow",
                nav_intent=target,
                **({"messages": msgs_update} if msgs_update else {}),
            )
        # resume / side_text -> let the subgraph redisplay / advance
        logger.info("supervisor_router: in-workflow %s -> subgraph", kind)
        return _dispatch(
            "request_access_subgraph",
            active_intent="request_access",
            mode="workflow",
            **({"messages": msgs_update} if msgs_update else {}),
        )

    # ---- 3) Fresh turn — LLM tool-call router --------------------------------
    if not text:
        logger.info("supervisor_router: fresh turn with no text — direct reply")
        return {"supervisor_decision": "direct_reply"}

    result = classify_fresh_turn_text(text)
    kind = result.get("kind")
    raw = result.get("raw_response")

    logger.info("supervisor_router: fresh turn kind=%s", kind)

    if kind == "start_access":
        return Command(
            update={
                "messages": [raw] if raw is not None else [],
                "supervisor_decision": "request_access_subgraph",
                "active_intent": "request_access",
                "active_flow": "request_access",
                "mode": "workflow",
                "ra_search_query": result.get("search_query") or text,
            },
            goto="request_access_subgraph",
        )
    if kind == "faq_kb":
        return Command(
            update={
                "messages": [raw] if raw is not None else [],
                "supervisor_decision": "faq_kb_agent",
                "active_intent": "faq",
                "mode": "faq",
            },
            goto="faq_kb_agent",
        )
    if kind == "general_web":
        return Command(
            update={
                "messages": [raw] if raw is not None else [],
                "supervisor_decision": "general_faq_tavily_agent",
                "active_intent": "general_faq",
                "mode": "faq",
            },
            goto="general_faq_tavily_agent",
        )
    if kind == "status_check":
        return Command(
            update={
                "messages": [raw] if raw is not None else [],
                "supervisor_decision": "status_agent",
                "active_intent": "status_check",
            },
            goto="status_agent",
        )

    # kind == "direct" — LLM declined to route; reply directly
    return {
        "messages": [raw] if raw is not None else [],
        "supervisor_decision": "direct_reply",
    }
