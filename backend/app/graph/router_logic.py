from __future__ import annotations

"""Routing classifiers for the parent supervisor and request-access subgraph.

All *natural-language intent classification* goes through a gpt-4o
tool-calling LLM. Structured button-click payloads (e.g.
``{"facet":"domain","value":"clinical"}`` or ``{"action":"submit"}``) are a
typed UI contract with the frontend and are dispatched deterministically —
routing them through an LLM would add latency, cost, and non-determinism
for no gain.

Two classifiers are exposed:

* :func:`classify_fresh_turn_text` — used by the parent supervisor on fresh
  turns with no paused workflow. Picks one of
  ``start_access`` / ``faq_kb`` / ``general_web`` / ``status_check`` /
  ``direct``.

* :func:`classify_workflow_text` — used while the request-access workflow is
  paused (either by the subgraph router when the user types free-text while a
  step is pending, or by the parent supervisor when a fresh HumanMessage
  arrives with ``active_flow == "request_access"``). Picks one of
  ``faq`` / ``general_web`` / ``nav`` (with ``nav_target``) / ``resume`` /
  ``side_text``.

:func:`classify_resume_value` wraps :func:`classify_workflow_text` and is the
entry point used by the request-access subgraph's intra-flow router.
"""

import logging
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.core.llm import get_chat_llm
from app.graph.prompts import (
    CLARIFY_FAQ_NO_QUESTION,
    CLARIFY_FAQ_WITH_QUESTION,
    CLARIFY_GENERIC_IN_WORKFLOW_SUFFIX,
    CLARIFY_GENERIC_MESSAGE,
    CLARIFY_NAV_DESCRIPTIONS,
    CLARIFY_NAV_FALLBACK,
    CLARIFY_NAV_TEMPLATE,
    CLARIFY_RESUME_MESSAGE,
    CLARIFY_START_ACCESS_NO_QUERY,
    CLARIFY_START_ACCESS_WITH_QUERY,
    CLARIFY_STATUS_NO_ID,
    CLARIFY_STATUS_WITH_ID,
    FRESH_TURN_SYSTEM_PROMPT,
    SCOPE_MESSAGE as _SCOPE_MESSAGE,
    WORKFLOW_TEXT_SYSTEM_TEMPLATE,
)
from app.graph.state import (
    RA_STEP_CHOOSE_ANONYMIZATION,
    RA_STEP_CHOOSE_DOMAIN,
    RA_STEP_CHOOSE_PRODUCTS,
    RA_STEP_NARROW_SEARCH,
    AppState,
)

logger = logging.getLogger(__name__)

ROUTING_MODEL = "gpt-4o"

# If an LLM tool-call's confidence is below this threshold, the supervisor
# asks the user for clarification instead of dispatching.
CONFIDENCE_THRESHOLD = 0.9

# Re-exported for callers that imported SCOPE_MESSAGE from this module
# before prompts were extracted into :mod:`app.graph.prompts`.
SCOPE_MESSAGE = _SCOPE_MESSAGE


def build_clarify_message(result: dict, *, in_workflow: bool = False) -> str:
    """Build a candidate-specific "Did you mean…?" clarification.

    Echoes back the intent the LLM *leaned* toward (``candidate_kind``) and
    any useful argument it extracted (search query, question text, etc.),
    then asks the user to confirm or rephrase. Falls back to a generic
    capability-list prompt if we don't have enough context.
    """
    candidate = result.get("candidate_kind") or ""

    if candidate == "start_access":
        q = (result.get("search_query") or "").strip()
        if q:
            return CLARIFY_START_ACCESS_WITH_QUERY.format(query=q)
        return CLARIFY_START_ACCESS_NO_QUERY

    if candidate == "faq_kb" or candidate == "faq":
        tc = result.get("tool_call") or {}
        args = tc.get("args") or {}
        q = (args.get("question") or result.get("text") or "").strip()
        if q:
            return CLARIFY_FAQ_WITH_QUESTION.format(question=q)
        return CLARIFY_FAQ_NO_QUESTION

    if candidate == "status_check":
        tc = result.get("tool_call") or {}
        args = tc.get("args") or {}
        rid = (result.get("request_id") or args.get("request_id") or "").strip()
        if rid:
            return CLARIFY_STATUS_WITH_ID.format(request_id=rid)
        return CLARIFY_STATUS_NO_ID

    if candidate == "nav":
        target = result.get("nav_target") or ""
        # CLARIFY_NAV_DESCRIPTIONS uses canonical step ids; map our RA_STEP_*
        # constants to the same keys so the lookup stays consistent if the
        # constants are ever renamed.
        key_map = {
            RA_STEP_CHOOSE_DOMAIN: "choose_domain",
            RA_STEP_CHOOSE_ANONYMIZATION: "choose_anonymization",
            RA_STEP_CHOOSE_PRODUCTS: "choose_products",
            "view_cart": "view_cart",
        }
        pretty = CLARIFY_NAV_DESCRIPTIONS.get(
            key_map.get(target, target), CLARIFY_NAV_FALLBACK
        )
        return CLARIFY_NAV_TEMPLATE.format(pretty=pretty)

    if candidate == "resume":
        return CLARIFY_RESUME_MESSAGE

    # Generic fallback — happens when the LLM declined to call any tool or
    # returned something we don't recognise.
    base = CLARIFY_GENERIC_MESSAGE
    if in_workflow:
        base += CLARIFY_GENERIC_IN_WORKFLOW_SUFFIX
    return base


# Short affirmative / negative responses to a "Did you mean…?" clarification.
# Kept intentionally small and deterministic — we only use these to decide
# whether to re-dispatch to a saved candidate intent, not to understand the
# general message. Anything else falls through to the normal classifier.
_AFFIRMATIVE_TOKENS = {
    "yes", "y", "yeah", "yep", "yup", "sure", "correct",
    "right", "that's right", "thats right", "confirmed", "confirm",
    "exactly", "absolutely", "please do", "go ahead", "proceed",
    "ok", "okay", "k",
}
_NEGATIVE_TOKENS = {
    "no", "n", "nope", "nah", "negative", "wrong",
    "not really", "that's not right", "thats not right",
    "cancel", "never mind", "nevermind", "don't", "dont",
}


def classify_yes_no(text: str) -> str | None:
    """Return ``"yes"``, ``"no"``, or ``None`` if the message is neither.

    Strict match against a small vocabulary — we only short-circuit when the
    user's message is a clean affirmation/negation to the prior clarify
    prompt. Anything longer (e.g. ``"yes but also…"``) returns ``None`` and
    falls through to the normal classifier.
    """
    if not text:
        return None
    t = text.strip().lower().rstrip("!.?")
    if not t:
        return None
    if t in _AFFIRMATIVE_TOKENS:
        return "yes"
    if t in _NEGATIVE_TOKENS:
        return "no"
    return None


def _coerce_confidence(raw: Any) -> float:
    """Clamp an LLM-provided confidence into [0.0, 1.0]; default 0.5."""
    try:
        c = float(raw)
    except (TypeError, ValueError):
        return 0.5
    if c < 0.0:
        return 0.0
    if c > 1.0:
        return 1.0
    return c


# ---------------------------------------------------------------------------
# Non-LLM helpers (structured / state)
# ---------------------------------------------------------------------------


def last_human_message(state: AppState) -> tuple[Any | None, str, dict]:
    """Return the most recent ``HumanMessage`` and its text/additional_kwargs."""
    for msg in reversed(state.get("messages", [])):
        if getattr(msg, "type", None) == "human":
            text = getattr(msg, "content", "") or ""
            if not isinstance(text, str):
                text = str(text)
            kwargs = getattr(msg, "additional_kwargs", None) or {}
            return msg, text, kwargs
    return None, "", {}


def nav_intent_from_resume_value(value: Any) -> str | None:
    """Deterministic map from a structured button-click payload to a nav target.

    This is a typed UI contract — *not* free-text classification — so it stays
    pure-Python.
    """
    if not isinstance(value, dict):
        return None
    action = value.get("action")
    if action == "refine_filters":
        # "Refine Filters" button routes back through the conversational
        # narrowing subagent — the chip nodes are no longer a front door.
        return RA_STEP_NARROW_SEARCH
    if action == "add_more":
        return RA_STEP_CHOOSE_PRODUCTS
    if action == "change_selection":
        return RA_STEP_CHOOSE_PRODUCTS
    if action == "view_cart":
        return "view_cart"
    return None


# ---------------------------------------------------------------------------
# Fresh-turn classifier (parent supervisor, no active workflow)
# ---------------------------------------------------------------------------


_FRESH_SYSTEM = SystemMessage(content=FRESH_TURN_SYSTEM_PROMPT)


@tool
def start_access_request(search_query: str, confidence: float = 0.5) -> str:
    """User wants to start a data-product access request."""
    return ""


@tool
def faq_kb_question(question: str, confidence: float = 0.5) -> str:
    """User is asking an internal KB / IHD / policy / process question."""
    return ""


@tool
def check_request_status(request_id: str = "", confidence: float = 0.5) -> str:
    """User is asking about the status of an existing access request."""
    return ""


@tool
def out_of_scope(reason: str = "", confidence: float = 0.5) -> str:
    """User's request is outside the assistant's supported capabilities."""
    return ""


_FRESH_TOOLS = [
    start_access_request,
    faq_kb_question,
    check_request_status,
    out_of_scope,
]

_fresh_llm = None


def _get_fresh_llm():
    global _fresh_llm
    if _fresh_llm is None:
        _fresh_llm = get_chat_llm(model=ROUTING_MODEL, temperature=0).bind_tools(_FRESH_TOOLS)
    return _fresh_llm


FreshTurnKind = Literal[
    "start_access",
    "faq_kb",
    "status_check",
    "out_of_scope",
    "clarify",
    "direct",
]


def classify_fresh_turn_text(text: str) -> dict:
    """Classify a fresh-turn message via gpt-4o tool calling.

    Returns a dict with:
      * ``kind``:            one of ``start_access`` / ``faq_kb`` /
                             ``status_check`` / ``out_of_scope`` /
                             ``clarify`` / ``direct``
      * ``confidence``:      float in [0.0, 1.0] reported by the LLM
      * ``search_query``:    set when ``kind == "start_access"``
      * ``request_id``:      set when ``kind == "status_check"`` (may be "")
      * ``reason``:          set when ``kind == "out_of_scope"``
      * ``raw_response``:    the LLM ``AIMessage`` (used by callers that want to
                             append it to the message history).

    When the LLM reports ``confidence < CONFIDENCE_THRESHOLD``, the ``kind``
    is overridden to ``"clarify"`` and the caller should ask the user for
    more detail instead of dispatching.
    """
    msg = HumanMessage(content=text or "")
    response = _get_fresh_llm().invoke([_FRESH_SYSTEM, msg])
    if not getattr(response, "tool_calls", None):
        logger.info("classify_fresh_turn_text: direct reply (no tool call)")
        return {"kind": "direct", "confidence": 0.0, "raw_response": response}

    tc = response.tool_calls[0]
    name = tc["name"]
    args = tc.get("args") or {}
    confidence = _coerce_confidence(args.get("confidence"))
    logger.info(
        "classify_fresh_turn_text: tool=%s confidence=%.2f args=%s",
        name, confidence, args,
    )

    kind: str
    extras: dict = {}
    if name == "start_access_request":
        kind = "start_access"
        extras["search_query"] = args.get("search_query") or text
    elif name == "faq_kb_question":
        kind = "faq_kb"
    elif name == "check_request_status":
        kind = "status_check"
        extras["request_id"] = args.get("request_id") or ""
    elif name == "out_of_scope":
        kind = "out_of_scope"
        extras["reason"] = args.get("reason") or ""
    else:
        return {"kind": "direct", "confidence": 0.0, "raw_response": response}

    # Out-of-scope responses go straight through — we don't want to ask for
    # clarification on a capability the assistant can't fulfil anyway.
    if kind != "out_of_scope" and confidence < CONFIDENCE_THRESHOLD:
        logger.info(
            "classify_fresh_turn_text: low confidence (%.2f < %.2f) -> clarify",
            confidence, CONFIDENCE_THRESHOLD,
        )
        return {
            "kind": "clarify",
            "candidate_kind": kind,
            "confidence": confidence,
            "raw_response": response,
            "tool_call": tc,
            **extras,
        }

    return {
        "kind": kind,
        "confidence": confidence,
        "raw_response": response,
        "tool_call": tc,
        **extras,
    }


# ---------------------------------------------------------------------------
# Paused-workflow classifier (subgraph + parent when active_flow active)
# ---------------------------------------------------------------------------


_WORKFLOW_SYSTEM_TEMPLATE = WORKFLOW_TEXT_SYSTEM_TEMPLATE


@tool
def ask_faq_kb(question: str, confidence: float = 0.5) -> str:
    """User is asking an internal KB / IHD / policy question during workflow."""
    return ""


@tool
def navigate_to_step(
    target: Literal[
        "choose_domain", "choose_anonymization", "choose_products", "view_cart"
    ],
    confidence: float = 0.5,
) -> str:
    """User wants to jump to a different step of the paused workflow."""
    return ""


@tool
def resume_workflow(confidence: float = 0.5) -> str:
    """User wants to resume / continue the paused workflow."""
    return ""


@tool
def side_remark(confidence: float = 0.5) -> str:
    """Short side comment or anything that doesn't fit the other categories."""
    return ""


@tool
def out_of_scope_workflow(reason: str = "", confidence: float = 0.5) -> str:
    """User's request is outside the assistant's supported capabilities."""
    return ""


_WORKFLOW_TOOLS = [
    ask_faq_kb,
    navigate_to_step,
    resume_workflow,
    side_remark,
    out_of_scope_workflow,
]

_workflow_llm = None


def _get_workflow_llm():
    global _workflow_llm
    if _workflow_llm is None:
        _workflow_llm = get_chat_llm(model=ROUTING_MODEL, temperature=0).bind_tools(
            _WORKFLOW_TOOLS
        )
    return _workflow_llm


WorkflowKind = Literal[
    "faq", "nav", "resume", "side_text", "out_of_scope", "clarify"
]

_NAV_TARGET_MAP: dict[str, str] = {
    # All "refine my narrowing" textual nav (change domain / change
    # anonymization / re-narrow) now routes through the conversational
    # ``narrow_search`` subagent rather than the legacy chip nodes. The
    # chip steps stay registered as graph nodes so existing structured
    # flows (e.g. invalidation rewinds) still work, but any nav by free
    # text goes through the purely-textual narrowing experience.
    "choose_domain": RA_STEP_NARROW_SEARCH,
    "choose_anonymization": RA_STEP_NARROW_SEARCH,
    "choose_products": RA_STEP_CHOOSE_PRODUCTS,
    "view_cart": "view_cart",
}


def classify_workflow_text(text: str, *, workflow_summary: str = "") -> dict:
    """Classify a free-text message sent during a paused request-access workflow.

    Returns a dict with:
      * ``kind``:         one of ``faq`` / ``nav`` / ``resume`` /
                          ``side_text`` / ``out_of_scope`` / ``clarify``
      * ``confidence``:   float in [0.0, 1.0] reported by the LLM
      * ``nav_target``:   set when ``kind == "nav"``
      * ``reason``:       set when ``kind == "out_of_scope"``
      * ``raw_response``: the LLM ``AIMessage``

    When the LLM reports ``confidence < CONFIDENCE_THRESHOLD`` (and the kind
    is not ``out_of_scope`` or ``side_text``), the kind is overridden to
    ``"clarify"`` and the caller should ask for more detail.
    """
    context = workflow_summary.strip() or "(no additional context)"
    system = SystemMessage(content=_WORKFLOW_SYSTEM_TEMPLATE.format(context=context))
    msg = HumanMessage(content=text or "")
    response = _get_workflow_llm().invoke([system, msg])
    if not getattr(response, "tool_calls", None):
        logger.info("classify_workflow_text: no tool call -> side_text")
        return {"kind": "side_text", "confidence": 0.0, "raw_response": response}

    tc = response.tool_calls[0]
    name = tc["name"]
    args = tc.get("args") or {}
    confidence = _coerce_confidence(args.get("confidence"))
    logger.info(
        "classify_workflow_text: tool=%s confidence=%.2f args=%s",
        name, confidence, args,
    )

    kind: str
    extras: dict = {}
    if name == "ask_faq_kb":
        kind = "faq"
    elif name == "navigate_to_step":
        kind = "nav"
        t = args.get("target") or "choose_domain"
        extras["nav_target"] = _NAV_TARGET_MAP.get(t, RA_STEP_NARROW_SEARCH)
    elif name == "resume_workflow":
        kind = "resume"
    elif name == "out_of_scope_workflow":
        kind = "out_of_scope"
        extras["reason"] = args.get("reason") or ""
    elif name == "side_remark":
        kind = "side_text"
    else:
        return {"kind": "side_text", "confidence": 0.0, "raw_response": response}

    # Side-remark and out-of-scope don't need clarification — they have their
    # own UX (re-display / scope message). The ambiguous kinds are the ones
    # that drive real state changes (faq / nav / resume).
    if kind in ("faq", "nav", "resume") and confidence < CONFIDENCE_THRESHOLD:
        logger.info(
            "classify_workflow_text: low confidence (%.2f < %.2f) -> clarify",
            confidence, CONFIDENCE_THRESHOLD,
        )
        return {
            "kind": "clarify",
            "candidate_kind": kind,
            "confidence": confidence,
            "raw_response": response,
            **extras,
        }

    return {
        "kind": kind,
        "confidence": confidence,
        "raw_response": response,
        **extras,
    }


# ---------------------------------------------------------------------------
# Resume-value classifier (subgraph router entry point)
# ---------------------------------------------------------------------------


def classify_resume_value(value: Any, *, workflow_summary: str = "") -> dict:
    """Classify a LangGraph resume value produced by ``Command(resume=…)``.

    Structured answer / nav payloads from button clicks are dispatched
    deterministically; free-text resume values (``{"action":"user_message",
    "text":…}`` or a bare string) are handed to the LLM classifier.

    Returns a dict with ``kind`` ∈
    ``answer | nav | faq | general_web | resume | user_text | unknown`` and
    optionally ``nav_target`` / ``text``.
    """
    if value is None:
        return {"kind": "unknown"}

    if isinstance(value, dict):
        # Free-text message wrapped by ChatService
        if value.get("action") == "user_message" and isinstance(value.get("text"), str):
            text = value["text"]
            res = classify_workflow_text(text, workflow_summary=workflow_summary)
            # Normalize the "side_text" bucket to "user_text" for router consumers
            if res.get("kind") == "side_text":
                res["kind"] = "user_text"
            res["text"] = text
            return res

        # Structured nav from button IDs
        nav = nav_intent_from_resume_value(value)
        if nav:
            return {"kind": "nav", "nav_target": nav}

        # Structured answers (facet chip, product multi-select, cart buttons,
        # confirmation buttons, form submit, MCP app results).
        if "facet" in value and "value" in value:
            return {"kind": "answer"}
        if value.get("action") in (
            "select",
            "fill_forms",
            "submit",
            "confirm",
            "edit",
            "cancel",
            "open_search",
        ):
            return {"kind": "answer"}
        if "selected_products" in value:
            return {"kind": "answer"}
        if isinstance(value.get("form_data"), dict) or isinstance(
            value.get("answers"), dict
        ):
            return {"kind": "answer"}
        return {"kind": "unknown"}

    if isinstance(value, str):
        res = classify_workflow_text(value, workflow_summary=workflow_summary)
        if res.get("kind") == "side_text":
            res["kind"] = "user_text"
        res["text"] = value
        return res

    return {"kind": "unknown"}
