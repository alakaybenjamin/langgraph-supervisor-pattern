from __future__ import annotations

"""Conversational narrowing subagent.

Replaces ``choose_domain`` + ``choose_anonymization`` in the default
request-access flow with a purely textual exchange — no chips, no
buttons. The agent decides what (if anything) is still missing, asks
the user one short question at a time, handles ambiguity (e.g. a bare
number that *might* be a study id), and finally commits the narrowed
filters before handing off to ``search_products``.

Design notes
------------
* The agent is hand-rolled (not ``create_agent``) so the whole flow
  stays inside a single LangGraph node and we can use a single
  ``interrupt()`` boundary per turn.
* Each call to :func:`narrow_search` performs **at most one**
  ``interrupt()`` call. After the user's reply comes back via
  ``Command(resume=…)`` (auto-wrapped by
  :mod:`app.service.chat_service`), the node updates ``narrow_state``
  with the new ``ToolMessage`` and routes to itself via
  ``Command(goto="narrow_search")``. The next execution is a fresh
  Python frame, so the ReAct-style loop is realised across multiple
  node runs rather than one runaway coroutine.
* This deliberately avoids the multi-``interrupt()``-in-one-node
  pattern, which forces LangGraph to re-execute the whole node body
  (including non-deterministic LLM calls) on every resume.

State contract
--------------
``narrow_state`` is owned end-to-end by this node. Shape::

    {
        "messages": [SystemMessage | AIMessage | ToolMessage, …],
        "turns": int,                # ask_user calls so far this session
        "pending_tc_id": str | None, # tool_call_id awaiting user reply
    }

Cleared (set to ``None``) on commit.
"""

import logging
import uuid
from typing import Any

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langgraph.types import Command, interrupt

from app.core.llm import get_chat_llm
from app.graph.state import (
    RA_STEP_NARROW_SEARCH,
    RA_STEP_SEARCH_PRODUCTS,
    AppState,
)
from app.graph.subgraphs.request_access.prompts import (
    NARROW_AGENT_SYSTEM_TEMPLATE,
)

logger = logging.getLogger(__name__)

_AGENT_MODEL = "gpt-4o"
# Defensive cap: at most this many ``ask_user`` round-trips per narrowing
# session. Past this, the node force-commits with whatever it has so a
# misbehaving LLM can never trap the user in an infinite question loop.
# Set to 4 so the agent can comfortably cover topic + the three optional
# facets (domain, anonymization, study_id) when the user wants to
# specify several of them. The system prompt encourages batching to
# stay well under this cap in normal use.
_MAX_TURNS = 4


# ---------------------------------------------------------------------------
# Tools the agent may call
# ---------------------------------------------------------------------------


@tool
def ask_user(message: str) -> str:
    """Ask the user a short follow-up question and wait for their reply.

    The ``message`` is shown to the user as a normal assistant chat
    bubble. Use this to request ONE missing piece of info, or to confirm
    an ambiguous value, at a time.
    """
    return ""


@tool
def commit_narrow(
    search_text: str = "",
    domain: str = "",
    anonymization: str = "",
    study_id: str = "",
) -> str:
    """Finalize the narrowing and run the search.

    Pass the empty string for any field the user did not state — it
    means "no filter for this dimension". Use canonical ids for
    ``domain`` and ``anonymization``.
    """
    return ""


# ---------------------------------------------------------------------------
# LLM lazy factory
# ---------------------------------------------------------------------------

_llm: Any | None = None


def _get_llm() -> Any:
    global _llm
    if _llm is None:
        _llm = get_chat_llm(model=_AGENT_MODEL, temperature=0).bind_tools(
            [ask_user, commit_narrow]
        )
    return _llm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Intent phrases that look like a search query but really just signal
# "I want to start a request". The supervisor often lifts these into
# ``ra_search_query`` verbatim. Treating them as a real topic gives the
# narrowing agent a false sense of "I know enough" and makes it commit
# straight away. Strip them out before they ever reach the system prompt.
_INTENT_NOISE: set[str] = {
    "request access",
    "request data access",
    "i need data",
    "i need access",
    "i need access to data",
    "i want data",
    "i want access",
    "i want to request",
    "i want to request access",
    "give me access",
    "give me data",
    "start",
    "begin",
    "new request",
    "data access",
    "help me find data",
    "help",
    "access",
    "data",
    "data products",
    "data product",
    "products",
    "product",
    "datasets",
    "dataset",
    "some data",
    "any data",
    "anything",
}


def _is_intent_noise(text: str) -> bool:
    """Return True if ``text`` is a generic 'start the workflow' phrase rather
    than a real search topic. Case-insensitive and tolerant of trailing
    punctuation.
    """
    cleaned = text.strip().lower().rstrip("?.!,;:")
    return cleaned in _INTENT_NOISE


def _facet_ids(cache: dict | None, key: str) -> list[str]:
    """Return canonical option ids for a facet from the prefetched cache."""
    if not isinstance(cache, dict):
        return []
    items = cache.get(key) or []
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for it in items:
        if isinstance(it, dict) and "id" in it:
            out.append(str(it["id"]))
    return out


def _format_known_facets(state: AppState) -> str:
    """Short bullet list of what the supervisor / earlier turns already gave us.

    Intent phrases ("request access" et al.) are filtered from the search
    keywords slot so the agent doesn't mistake them for a real topic.
    """
    bits: list[str] = []
    if sd := [d for d in (state.get("selected_domains") or []) if d and d != "all"]:
        bits.append(f"  - domain: {sd[0]}")
    if sa := state.get("selected_anonymization"):
        bits.append(f"  - anonymization: {sa}")
    if sid := state.get("ra_study_id"):
        bits.append(f"  - study_id: {sid}")
    q = (state.get("ra_search_query") or "").strip()
    if q and q != "*" and not _is_intent_noise(q):
        bits.append(f"  - search keywords: {q}")
    return "\n".join(bits) if bits else "  (nothing yet — start fresh)"


def _build_system_prompt(state: AppState) -> SystemMessage:
    cache = state.get("mcp_facet_cache") or {}
    domains = ", ".join(_facet_ids(cache, "domains")) or "(unknown)"
    anonymizations = (
        ", ".join(_facet_ids(cache, "anonymization")) or "(unknown)"
    )
    return SystemMessage(
        content=NARROW_AGENT_SYSTEM_TEMPLATE.format(
            domains=domains,
            anonymizations=anonymizations,
            known_facets=_format_known_facets(state),
        )
    )


def _seed_initial_user_message(state: AppState) -> HumanMessage:
    """Frame the agent's first turn with whatever the user already said.

    Priority order:
      1. ``narrow_refine_hint`` — set when the user navigated BACK to
         re-narrow via plain chat (e.g. "change anonymization to
         identified"). The agent should act on this directly rather
         than re-asking a generic question.
      2. ``ra_search_query`` — supervisor-extracted search text from
         the original request.
      3. Generic fallback.
    """
    hint = (state.get("narrow_refine_hint") or "").strip()
    if hint:
        return HumanMessage(
            content=(
                f'The user wants to refine/change their narrowing filters '
                f'and said: "{hint}". Apply the change (e.g. update the '
                f'relevant facet) and commit, asking at most one '
                f'clarifying question only if strictly necessary.'
            )
        )
    raw = (state.get("ra_search_query") or "").strip()
    if raw and raw != "*" and not _is_intent_noise(raw):
        content = f'The user said: "{raw}".'
    else:
        content = (
            "The user wants to start a data-product access request but "
            "did not specify a topic yet. Ask them what kind of data "
            "they're looking for."
        )
    return HumanMessage(content=content)


def _extract_user_reply(resume_value: Any) -> str:
    """Pull the user's text out of whatever ``interrupt()`` returned.

    ``chat_service`` wraps free-text replies as
    ``{"action": "user_message", "text": "…"}``. Structured resumes
    (e.g. nav buttons) are coerced to a best-effort string so the agent
    can still react sensibly.
    """
    if resume_value is None:
        return ""
    if isinstance(resume_value, str):
        return resume_value
    if isinstance(resume_value, dict):
        text = resume_value.get("text")
        if isinstance(text, str):
            return text
        return str(resume_value)
    return str(resume_value)


def _normalize_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _commit(args: dict, state: AppState, ns: dict | None) -> Command:
    """Build the Command that hands off to ``search_products`` with the
    finalized narrowing payload. Always clears ``narrow_state``.
    """
    explicit_search = _normalize_str(args.get("search_text"))
    fallback_query = (state.get("ra_search_query") or "").strip()
    if fallback_query and _is_intent_noise(fallback_query):
        fallback_query = ""
    search_text = explicit_search or fallback_query or "*"
    domain = _normalize_str(args.get("domain"))
    anonymization = _normalize_str(args.get("anonymization"))
    study_id = _normalize_str(args.get("study_id")) or (
        state.get("ra_study_id") or ""
    )
    update: dict[str, Any] = {
        "ra_search_query": search_text,
        "ra_study_id": study_id,
        "selected_anonymization": anonymization or state.get("selected_anonymization"),
        "selected_domains": (
            [domain] if domain else (state.get("selected_domains") or [])
        ),
        "narrow_state": None,
        "narrow_refine_hint": None,
        "current_step": RA_STEP_SEARCH_PRODUCTS,
        "last_workflow_node": "narrow_search",
        "last_resume_value": None,
        "pending_prompt": None,
        "awaiting_input": False,
        "active_flow": "request_access",
        "mode": "workflow",
    }
    logger.info(
        "narrow_search: commit search=%r domain=%r anon=%r study_id=%r turns=%d",
        search_text, domain, anonymization, study_id,
        (ns or {}).get("turns", 0),
    )
    return Command(update=update, goto="search_products")


# ---------------------------------------------------------------------------
# Node entry point
# ---------------------------------------------------------------------------


async def narrow_search(state: AppState) -> Command:
    """Run one step of the narrowing conversation.

    Lifecycle per execution:
      1. Load (or seed) ``narrow_state``.
      2. If a previous turn left a ``pending_tc_id``, fold the user's
         most recent reply into the agent's message log.
      3. Defensive turn cap → force-commit.
      4. Single LLM call. Either:
           * commit_narrow / no-tool  → handoff to ``search_products``.
           * ask_user                 → emit ``narrow_message``
             interrupt and pause; on resume, route back to ``narrow_search``.
    """
    ns = state.get("narrow_state")
    if ns is None:
        ns = {
            "messages": [
                _build_system_prompt(state),
                _seed_initial_user_message(state),
            ],
            "turns": 0,
            "pending_tc_id": None,
        }

    # Step 2: fold the user's reply into the agent's transcript.
    pending = ns.get("pending_tc_id")
    if pending:
        reply = _extract_user_reply(state.get("last_resume_value"))
        ns["messages"].append(
            ToolMessage(content=reply or "(no reply)", tool_call_id=pending)
        )
        ns["pending_tc_id"] = None

    # Step 3: defensive cap.
    if ns.get("turns", 0) >= _MAX_TURNS:
        logger.warning(
            "narrow_search: turn cap (%d) hit — force-committing", _MAX_TURNS
        )
        return _commit({}, state, ns)

    # Step 4: ask the LLM what to do next.
    try:
        response = await _get_llm().ainvoke(ns["messages"])
    except Exception:  # noqa: BLE001
        logger.exception("narrow_search: LLM call failed — force-committing")
        return _commit({}, state, ns)

    ns["messages"].append(response)
    tcs = getattr(response, "tool_calls", None) or []

    if not tcs:
        # The agent broke the contract and replied in plain text. Commit
        # with whatever we have rather than dead-ending the user.
        logger.warning("narrow_search: LLM returned no tool call — force-committing")
        return _commit({}, state, ns)

    tc = tcs[0]
    name = tc.get("name")
    args = tc.get("args") or {}

    if name == "commit_narrow":
        return _commit(args, state, ns)

    if name == "ask_user":
        message = _normalize_str(args.get("message")) or (
            "Anything else I should narrow on (domain, anonymization, study id)?"
        )
        ns["turns"] = ns.get("turns", 0) + 1
        ns["pending_tc_id"] = tc.get("id") or str(uuid.uuid4())
        prompt_id = str(uuid.uuid4())
        payload = {
            "type": "narrow_message",
            "message": message,
            "step": RA_STEP_NARROW_SEARCH,
            "prompt_id": prompt_id,
        }
        logger.info(
            "narrow_search: asking user (turn %d/%d, tc_id=%s): %r",
            ns["turns"], _MAX_TURNS, ns["pending_tc_id"], message,
        )
        # Pause for the user's typed reply. ``chat_service`` wraps it as
        # ``Command(resume={"action": "user_message", "text": ...})`` and
        # routes it straight back here.
        reply = interrupt(payload)
        # On resume, persist the freshly-arrived ``narrow_state`` (with
        # the AIMessage and pending_tc_id) plus the resume value, then
        # bounce back into ``narrow_search`` for a clean new execution
        # frame. This keeps each node run to a single ``interrupt()``.
        return Command(
            update={
                "narrow_state": ns,
                "last_resume_value": reply,
                "current_step": RA_STEP_NARROW_SEARCH,
                "last_workflow_node": "narrow_search",
                "active_flow": "request_access",
                "mode": "workflow",
                "awaiting_input": False,
                "pending_prompt": None,
            },
            goto="narrow_search",
        )

    # Unknown tool — give up gracefully.
    logger.warning("narrow_search: unknown tool call %r — force-committing", name)
    return _commit({}, state, ns)
