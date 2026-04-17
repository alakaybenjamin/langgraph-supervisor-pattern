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
   - ``faq``         → ``faq_kb_agent``
   - ``nav``         → subgraph, with ``nav_intent`` set
   - ``resume`` / ``side_text`` → subgraph, which redisplays the pending step
   - ``out_of_scope``→ direct reply with the capability list, workflow stays paused
   - ``clarify``     → direct reply asking for more detail (confidence < 0.9)
3. **Fresh turn** (no active workflow) — uses
   :func:`classify_fresh_turn_text` (gpt-4o) to decide between:
   - ``start_access`` → subgraph
   - ``faq_kb``       → ``faq_kb_agent``
   - ``status_check`` → ``status_agent``
   - ``out_of_scope`` → direct reply with the capability list
   - ``clarify`` / ``direct`` → direct reply asking the user to rephrase
"""

import logging
from typing import Literal

from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.graph.prompts import CLARIFY_DECLINED_MESSAGE, SCOPE_MESSAGE
from app.graph.router_logic import (
    build_clarify_message,
    classify_fresh_turn_text,
    classify_workflow_text,
    classify_yes_no,
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
    "pending_clarification": None,
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
    # Any successful dispatch clears an outstanding "Did you mean…?" so it
    # doesn't re-trigger on the following turn.
    update.setdefault("pending_clarification", None)
    return Command(update=update, goto=target)


def _reply_and_end(
    text: str,
    decision: str,
    extra_messages: list | None = None,
    extra_update: dict | None = None,
) -> dict:
    """Produce a direct assistant reply and end the turn (no goto)."""
    msgs = list(extra_messages or [])
    msgs.append(AIMessage(content=text))
    out: dict = {
        "messages": msgs,
        "supervisor_decision": decision,
    }
    if extra_update:
        out.update(extra_update)
    return out


def _dispatch_from_clarification(
    pc: dict, text: str
) -> Command:
    """Dispatch the saved candidate intent from a prior clarify reply.

    ``pc`` is the dict we saved in ``pending_clarification`` when we emitted
    the "Did you mean…?" message. ``text`` is the user's (affirmative) next
    turn — we include it as the fresh search query / question so the target
    sibling sees the same text it would have seen without the clarify
    detour.
    """
    candidate = pc.get("candidate_kind")
    logger.info(
        "supervisor_router: user confirmed pending_clarification (candidate=%s)",
        candidate,
    )
    clear = {"pending_clarification": None}

    if candidate == "start_access":
        return Command(
            update={
                **clear,
                "supervisor_decision": "request_access_subgraph",
                "active_intent": "request_access",
                "active_flow": "request_access",
                "mode": "workflow",
                "ra_search_query": pc.get("search_query") or text,
            },
            goto="request_access_subgraph",
        )
    if candidate in ("faq_kb", "faq"):
        return Command(
            update={
                **clear,
                "supervisor_decision": "faq_kb_agent",
                "active_intent": "faq",
                "mode": "faq",
            },
            goto="faq_kb_agent",
        )
    if candidate == "status_check":
        return Command(
            update={
                **clear,
                "supervisor_decision": "status_agent",
                "active_intent": "status_check",
                "last_request_id": pc.get("request_id") or "",
            },
            goto="status_agent",
        )
    if candidate == "nav" and pc.get("nav_target"):
        return Command(
            update={
                **clear,
                "supervisor_decision": "request_access_subgraph",
                "active_intent": "request_access",
                "mode": "workflow",
                "nav_intent": pc.get("nav_target"),
            },
            goto="request_access_subgraph",
        )
    if candidate == "resume":
        return Command(
            update={
                **clear,
                "supervisor_decision": "request_access_subgraph",
                "active_intent": "request_access",
                "mode": "workflow",
            },
            goto="request_access_subgraph",
        )
    # Unknown candidate — clear and fall back to the generic clarify reply.
    return Command(
        update={**clear, "supervisor_decision": "clarify"},
        goto="__end__",
    )


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


def _pack_pending_clarification(result: dict) -> dict:
    """Subset of the classifier result we need to re-dispatch on 'yes'."""
    tc_args = (result.get("tool_call") or {}).get("args") or {}
    return {
        "candidate_kind": result.get("candidate_kind"),
        "search_query": result.get("search_query") or tc_args.get("search_query") or "",
        "question": tc_args.get("question") or "",
        "request_id": result.get("request_id") or tc_args.get("request_id") or "",
        "nav_target": result.get("nav_target") or "",
    }


def supervisor_router(state: AppState) -> Command[_SupervisorTarget] | dict:
    msg, text, kwargs = last_human_message(state)
    text = (text or "").strip()

    # ---- 0) Follow-up to a prior clarification ------------------------------
    # If the previous supervisor turn emitted a "Did you mean…?" reply we
    # remembered the candidate intent. Detect a short yes/no and act on it
    # here BEFORE consulting the LLM — otherwise a bare "yes" classifies as
    # out_of_scope.
    pc = state.get("pending_clarification")
    if isinstance(pc, dict) and pc.get("candidate_kind"):
        yn = classify_yes_no(text)
        if yn == "yes":
            return _dispatch_from_clarification(pc, text)
        if yn == "no":
            logger.info("supervisor_router: user declined pending_clarification")
            return _reply_and_end(
                CLARIFY_DECLINED_MESSAGE,
                decision="clarify_declined",
                extra_update={"pending_clarification": None},
            )
        # Any other text: clear the pending clarification and run the
        # classifier on the new message (the user rephrased).
        logger.info(
            "supervisor_router: pending_clarification present but message is not yes/no — re-classifying"
        )
        # Fall through; we still clear pending_clarification via the dispatch
        # below (every branch sets it to None in its update).

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
        conf = result.get("confidence", 0.0)
        msgs_update = [raw] if raw is not None else []

        if kind == "out_of_scope":
            logger.info(
                "supervisor_router: in-workflow out_of_scope conf=%.2f", conf,
            )
            return _reply_and_end(
                SCOPE_MESSAGE,
                decision="out_of_scope",
                extra_messages=msgs_update,
                extra_update={"pending_clarification": None},
            )
        if kind == "clarify":
            logger.info(
                "supervisor_router: in-workflow clarify (candidate=%s, conf=%.2f)",
                result.get("candidate_kind"), conf,
            )
            return _reply_and_end(
                build_clarify_message(result, in_workflow=True),
                decision="clarify",
                extra_messages=msgs_update,
                extra_update={
                    "pending_clarification": _pack_pending_clarification(result),
                },
            )
        if kind == "faq":
            logger.info("supervisor_router: in-workflow FAQ -> faq_kb_agent")
            return _dispatch(
                "faq_kb_agent",
                mode="faq",
                active_intent="faq",
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
    conf = result.get("confidence", 0.0)
    msgs_update = [raw] if raw is not None else []

    logger.info("supervisor_router: fresh turn kind=%s conf=%.2f", kind, conf)

    if kind == "out_of_scope":
        return _reply_and_end(
            SCOPE_MESSAGE,
            decision="out_of_scope",
            extra_messages=msgs_update,
            extra_update={"pending_clarification": None},
        )
    if kind == "clarify":
        logger.info(
            "supervisor_router: fresh clarify (candidate=%s)",
            result.get("candidate_kind"),
        )
        return _reply_and_end(
            build_clarify_message(result, in_workflow=False),
            decision="clarify",
            extra_messages=msgs_update,
            extra_update={
                "pending_clarification": _pack_pending_clarification(result),
            },
        )
    if kind == "start_access":
        return Command(
            update={
                "messages": msgs_update,
                "supervisor_decision": "request_access_subgraph",
                "active_intent": "request_access",
                "active_flow": "request_access",
                "mode": "workflow",
                "ra_search_query": result.get("search_query") or text,
                "pending_clarification": None,
            },
            goto="request_access_subgraph",
        )
    if kind == "faq_kb":
        return Command(
            update={
                "messages": msgs_update,
                "supervisor_decision": "faq_kb_agent",
                "active_intent": "faq",
                "mode": "faq",
                "pending_clarification": None,
            },
            goto="faq_kb_agent",
        )
    if kind == "status_check":
        return Command(
            update={
                "messages": msgs_update,
                "supervisor_decision": "status_agent",
                "active_intent": "status_check",
                "pending_clarification": None,
            },
            goto="status_agent",
        )

    # kind == "direct" — LLM declined to route; ask user to clarify with the
    # generic capability prompt.
    return _reply_and_end(
        build_clarify_message({}, in_workflow=False),
        decision="direct_reply",
        extra_messages=msgs_update,
    )
