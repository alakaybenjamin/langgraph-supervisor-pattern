from __future__ import annotations

"""LLM-based search-intent extractor for the request-access subgraph.

Runs as a pure (non-HITL) node between ``choose_anonymization`` and
``search_products``. Takes the user's free-text search query (typed in the
start-access message or passed through from earlier turns) and produces
two cleaned fields:

- ``ra_search_query`` — concise keyword string suitable for substring
  search over product title / description. ``'*'`` when no usable
  keywords were present.
- ``ra_study_id``     — clinical study id (e.g. ``dp-501``) when it
  clearly appears in the text, else empty string.

Uses gpt-4o tool-calling (same model as the supervisor) so the extraction
logic stays LLM-driven and can handle arbitrary phrasings without a
growing regex ladder. Falls back to passing the raw query through
unchanged on transport / protocol error so search never hard-fails.
"""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.types import Command

from app.core.llm import get_chat_llm
from app.graph.state import RA_STEP_SEARCH_PRODUCTS, AppState
from app.graph.subgraphs.request_access.prompts import SEARCH_INTENT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_EXTRACTION_MODEL = "gpt-4o"


@tool
def set_search_intent(search_text: str, study_id: str = "") -> str:
    """Report the extracted search text and (optional) study id.

    Call this tool exactly once; return ``search_text='*'`` when the
    user's text has no usable keywords, and leave ``study_id`` empty
    unless the text clearly contains one.
    """
    return ""


_SYSTEM = SystemMessage(content=SEARCH_INTENT_SYSTEM_PROMPT)
_llm: Any | None = None


def _get_llm() -> Any:
    global _llm
    if _llm is None:
        _llm = get_chat_llm(
            model=_EXTRACTION_MODEL, temperature=0
        ).bind_tools([set_search_intent])
    return _llm


def extract_search_intent(text: str) -> dict[str, str]:
    """Return ``{"search_text": ..., "study_id": ...}`` for the given text.

    Never raises — falls back to ``{"search_text": text or "*", "study_id": ""}``
    on any LLM / transport error.
    """
    msg = HumanMessage(content=text or "")
    try:
        response = _get_llm().invoke([_SYSTEM, msg])
    except Exception:  # noqa: BLE001
        logger.exception("extract_search_intent: LLM call failed")
        return {"search_text": (text or "").strip() or "*", "study_id": ""}

    tool_calls = getattr(response, "tool_calls", None) or []
    if not tool_calls:
        logger.info("extract_search_intent: LLM returned no tool call")
        return {"search_text": (text or "").strip() or "*", "study_id": ""}

    args = tool_calls[0].get("args") or {}
    search_text = (args.get("search_text") or "").strip() or "*"
    study_id = (args.get("study_id") or "").strip()
    logger.info(
        "extract_search_intent: input=%r -> search_text=%r study_id=%r",
        text, search_text, study_id,
    )
    return {"search_text": search_text, "study_id": study_id}


def extract_search_intent_node(state: AppState) -> Command:
    """Pre-search node: normalize ``ra_search_query`` and derive ``ra_study_id``.

    Pure state transform — does not interrupt. Writes both fields even when
    the extractor returns the original text unchanged so downstream nodes
    have consistent inputs.
    """
    raw = (state.get("ra_search_query") or "").strip()
    intent = extract_search_intent(raw)
    return Command(
        update={
            "ra_search_query": intent["search_text"],
            "ra_study_id": intent["study_id"],
            "current_step": RA_STEP_SEARCH_PRODUCTS,
            "last_workflow_node": "extract_search_intent",
        },
        goto="search_products",
    )
