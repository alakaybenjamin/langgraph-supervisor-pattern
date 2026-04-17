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
from app.graph.state import (
    RA_STEP_CHOOSE_ANONYMIZATION,
    RA_STEP_CHOOSE_DOMAIN,
    RA_STEP_CHOOSE_PRODUCTS,
    AppState,
)

logger = logging.getLogger(__name__)

ROUTING_MODEL = "gpt-4o"


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
        return RA_STEP_CHOOSE_DOMAIN
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


_FRESH_SYSTEM = SystemMessage(content="""\
You are the top-level router for a Data Governance assistant. Classify the
user's latest message by calling exactly ONE tool. Do not reply directly
unless the intent is genuinely unclear; in that case, don't call any tool
and the system will ask the user to clarify.

Tools:
- `start_access_request(search_query)`: The user wants to request access to
  a data product / dataset / catalog item. `search_query` should be a short
  free-text query summarising what they're asking about.
- `faq_kb_question(question)`: The user is asking a question about our
  internal knowledge base — IHD process, data governance policy, SOPs,
  procedures, org-specific topics.
- `general_web_question(question)`: The user is asking a general-knowledge
  or current-events question (news, weather, prices, "who is …", unrelated
  to the IHD process).
- `check_request_status(request_id)`: The user is asking about the status of
  an existing access request (may or may not include a request id).

Be decisive. Prefer calling a tool over replying directly.\
""")


@tool
def start_access_request(search_query: str) -> str:
    """User wants to start a data-product access request."""
    return ""


@tool
def faq_kb_question(question: str) -> str:
    """User is asking an internal KB / IHD / policy / process question."""
    return ""


@tool
def general_web_question(question: str) -> str:
    """User is asking a general-knowledge or current-events question."""
    return ""


@tool
def check_request_status(request_id: str = "") -> str:
    """User is asking about the status of an existing access request."""
    return ""


_FRESH_TOOLS = [
    start_access_request,
    faq_kb_question,
    general_web_question,
    check_request_status,
]

_fresh_llm = None


def _get_fresh_llm():
    global _fresh_llm
    if _fresh_llm is None:
        _fresh_llm = get_chat_llm(model=ROUTING_MODEL, temperature=0).bind_tools(_FRESH_TOOLS)
    return _fresh_llm


FreshTurnKind = Literal["start_access", "faq_kb", "general_web", "status_check", "direct"]


def classify_fresh_turn_text(text: str) -> dict:
    """Classify a fresh-turn message via gpt-4o tool calling.

    Returns a dict with:
      * ``kind``:            one of ``start_access`` / ``faq_kb`` / ``general_web`` /
                             ``status_check`` / ``direct``
      * ``search_query``:    set when ``kind == "start_access"``
      * ``request_id``:      set when ``kind == "status_check"`` (may be "")
      * ``raw_response``:    the LLM ``AIMessage`` (used by callers that want to
                             append it to the message history, e.g. to emit a
                             tool-call trace).
    """
    msg = HumanMessage(content=text or "")
    response = _get_fresh_llm().invoke([_FRESH_SYSTEM, msg])
    if not getattr(response, "tool_calls", None):
        logger.info("classify_fresh_turn_text: direct reply (no tool call)")
        return {"kind": "direct", "raw_response": response}

    tc = response.tool_calls[0]
    name = tc["name"]
    args = tc.get("args") or {}
    logger.info("classify_fresh_turn_text: tool=%s args=%s", name, args)

    if name == "start_access_request":
        return {
            "kind": "start_access",
            "search_query": args.get("search_query") or text,
            "raw_response": response,
            "tool_call": tc,
        }
    if name == "faq_kb_question":
        return {"kind": "faq_kb", "raw_response": response, "tool_call": tc}
    if name == "general_web_question":
        return {"kind": "general_web", "raw_response": response, "tool_call": tc}
    if name == "check_request_status":
        return {
            "kind": "status_check",
            "request_id": args.get("request_id") or "",
            "raw_response": response,
            "tool_call": tc,
        }
    return {"kind": "direct", "raw_response": response}


# ---------------------------------------------------------------------------
# Paused-workflow classifier (subgraph + parent when active_flow active)
# ---------------------------------------------------------------------------


_WORKFLOW_SYSTEM_TEMPLATE = """\
You are the intra-workflow router for a Data Governance assistant's
request-access workflow.

The user has already started an access request and the workflow is paused
on a specific step, awaiting their next input. Classify the user's
free-text message by calling exactly ONE tool.

Current workflow context:
{context}

Tools:
- `ask_faq_kb(question)`: The user is asking a question about our internal
  knowledge base — IHD process, data governance policy, SOPs, procedures.
  After answering, the workflow stays paused and they can resume.
- `ask_general_web(question)`: The user is asking a general-knowledge or
  current-events question unrelated to the IHD process.
- `navigate_to_step(target)`: The user wants to jump to a different step of
  the paused workflow. `target` must be one of:
    * "choose_domain"         — redo the domain choice (re-choose data domain)
    * "choose_anonymization"  — redo the anonymization / data-handling choice
    * "choose_products"       — add/change/remove selected products
    * "view_cart"             — just view their current selection read-only
- `resume_workflow()`: The user explicitly wants to resume / continue the
  paused workflow (e.g. "continue", "keep going", "let's proceed").
- `side_remark()`: Short side-comment, typo, chit-chat, acknowledgement
  ("ok", "thanks"), or anything that does NOT fit the categories above.
  The workflow stays paused and we re-display the pending prompt.

Be decisive. If unsure between `ask_faq_kb` and `side_remark`, pick
`ask_faq_kb` only when the message is clearly a question about process,
policy, or governance.\
"""


@tool
def ask_faq_kb(question: str) -> str:
    """User is asking an internal KB / IHD / policy question during workflow."""
    return ""


@tool
def ask_general_web(question: str) -> str:
    """User is asking a general-knowledge question during workflow."""
    return ""


@tool
def navigate_to_step(
    target: Literal[
        "choose_domain", "choose_anonymization", "choose_products", "view_cart"
    ]
) -> str:
    """User wants to jump to a different step of the paused workflow."""
    return ""


@tool
def resume_workflow() -> str:
    """User wants to resume / continue the paused workflow."""
    return ""


@tool
def side_remark() -> str:
    """Short side comment or anything that doesn't fit the other categories."""
    return ""


_WORKFLOW_TOOLS = [
    ask_faq_kb,
    ask_general_web,
    navigate_to_step,
    resume_workflow,
    side_remark,
]

_workflow_llm = None


def _get_workflow_llm():
    global _workflow_llm
    if _workflow_llm is None:
        _workflow_llm = get_chat_llm(model=ROUTING_MODEL, temperature=0).bind_tools(
            _WORKFLOW_TOOLS
        )
    return _workflow_llm


WorkflowKind = Literal["faq", "general_web", "nav", "resume", "side_text"]

_NAV_TARGET_MAP: dict[str, str] = {
    "choose_domain": RA_STEP_CHOOSE_DOMAIN,
    "choose_anonymization": RA_STEP_CHOOSE_ANONYMIZATION,
    "choose_products": RA_STEP_CHOOSE_PRODUCTS,
    "view_cart": "view_cart",
}


def classify_workflow_text(text: str, *, workflow_summary: str = "") -> dict:
    """Classify a free-text message sent during a paused request-access workflow.

    Returns a dict with:
      * ``kind``:         one of ``faq`` / ``general_web`` / ``nav`` / ``resume`` /
                          ``side_text``
      * ``nav_target``:   set when ``kind == "nav"``, one of the RA step ids or
                          ``"view_cart"``
      * ``raw_response``: the LLM ``AIMessage``
    """
    context = workflow_summary.strip() or "(no additional context)"
    system = SystemMessage(content=_WORKFLOW_SYSTEM_TEMPLATE.format(context=context))
    msg = HumanMessage(content=text or "")
    response = _get_workflow_llm().invoke([system, msg])
    if not getattr(response, "tool_calls", None):
        logger.info("classify_workflow_text: no tool call -> side_text")
        return {"kind": "side_text", "raw_response": response}

    tc = response.tool_calls[0]
    name = tc["name"]
    args = tc.get("args") or {}
    logger.info("classify_workflow_text: tool=%s args=%s", name, args)

    if name == "ask_faq_kb":
        return {"kind": "faq", "raw_response": response}
    if name == "ask_general_web":
        return {"kind": "general_web", "raw_response": response}
    if name == "navigate_to_step":
        t = args.get("target") or "choose_domain"
        return {
            "kind": "nav",
            "nav_target": _NAV_TARGET_MAP.get(t, RA_STEP_CHOOSE_DOMAIN),
            "raw_response": response,
        }
    if name == "resume_workflow":
        return {"kind": "resume", "raw_response": response}
    return {"kind": "side_text", "raw_response": response}


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
