from __future__ import annotations

"""Sibling FAQ agents under the parent supervisor.

- ``faq_kb_agent`` — answers IHD / process / policy / governance questions
  using the Tavily-backed ``FaqService`` (KB-style). Today this is a single
  LLM synthesis step over Tavily results; the retrieval layer can be swapped
  for a Chroma/RAG KB without changing the graph.
- ``general_faq_tavily_agent`` — used for clearly standalone general-knowledge
  or current-events questions. Same backend today, but kept as a separate
  node so routing and future model selection can diverge cleanly.

Both preserve any paused request-access state: they only append an
``AIMessage`` and never clear ``pending_prompt`` / ``awaiting_input``.
"""

import logging

from langchain_core.messages import AIMessage

from app.core.llm import get_chat_llm
from app.graph.router_logic import last_human_message
from app.graph.state import AppState

logger = logging.getLogger(__name__)


def _faq_service():
    from app.service.faq_service import FaqService
    return FaqService()


# Tool names used by the gpt-4o routing classifiers whose ``question`` /
# ``search_query`` arg carries the real user question. Kept in sync with
# ``app.graph.router_logic``.
_FAQ_TOOL_NAMES = {
    # Parent supervisor fresh-turn classifier
    "faq_kb_question",
    "general_web_question",
    # Subgraph workflow-text classifier
    "ask_faq_kb",
    "ask_general_web",
}


def _extract_question(state: AppState) -> str:
    """Extract the real user question.

    Priority:

    1. The most recent ``AIMessage`` with a routing tool-call — its
       ``question`` argument is the text the router classified, which is
       always the user's *current* question (even on resume, where no new
       ``HumanMessage`` is appended to state).
    2. Resume value in ``last_resume_value`` (``{"action": "user_message",
       "text": ...}``) — set by the subgraph router before handoff.
    3. Last ``HumanMessage`` in state (fresh-turn fallback).
    """
    messages = state.get("messages", [])
    for msg in reversed(messages):
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            continue
        for tc in tool_calls:
            if tc.get("name") in _FAQ_TOOL_NAMES:
                args = tc.get("args") or {}
                q = args.get("question") or args.get("search_query") or ""
                if q:
                    return q
        # Stop walking past the most recent AIMessage that had tool-calls;
        # older tool-calls belong to prior turns and would leak stale
        # questions.
        break

    resume_val = state.get("last_resume_value")
    if isinstance(resume_val, dict) and resume_val.get("action") == "user_message":
        text = resume_val.get("text")
        if isinstance(text, str) and text:
            return text

    _, text, _ = last_human_message(state)
    return text


def _synthesize(question: str, context: str, *, system_prompt: str) -> str:
    llm = get_chat_llm()
    prompt = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Question: {question}\n\nSearch results:\n{context}"},
    ]
    return llm.invoke(prompt).content or ""


def faq_kb_agent(state: AppState) -> dict:
    """KB / IHD process FAQ agent (sibling of request-access)."""
    question = _extract_question(state)
    logger.info("faq_kb_agent: question=%r (active_flow=%s)", question, state.get("active_flow"))

    svc = _faq_service()
    results = svc.search(question)
    context = "\n\n".join(
        f"Source: {r.get('url', 'N/A')}\n{r.get('content', '')}" for r in results
    )

    system_prompt = (
        "You are a Data Governance / IHD knowledge-base assistant. "
        "Answer the user's question concisely using the search results below. "
        "If the results don't cover the question, say so honestly and suggest "
        "where to look. Keep the answer short (3-8 sentences) and professional. "
        "The user may be in the middle of a data access request — do NOT tell "
        "them to abandon or restart it; their workflow stays paused."
    )

    answer = _synthesize(question, context, system_prompt=system_prompt)

    update: dict = {"messages": [AIMessage(content=answer)], "mode": "faq"}
    summary = state.get("paused_workflow_summary") or ""
    if state.get("active_flow") == "request_access" and state.get("awaiting_input") and summary:
        update["messages"][0] = AIMessage(
            content=answer + f"\n\n_Your access request is still paused: {summary}_"
        )
    return update


def general_faq_tavily_agent(state: AppState) -> dict:
    """Standalone general-knowledge / current-events agent (Tavily)."""
    question = _extract_question(state)
    logger.info("general_faq_tavily_agent: question=%r", question)

    svc = _faq_service()
    results = svc.search(question)
    context = "\n\n".join(
        f"Source: {r.get('url', 'N/A')}\n{r.get('content', '')}" for r in results
    )

    system_prompt = (
        "You are a concise general-knowledge assistant. Use the web search "
        "results to answer the user's question in 3-8 sentences. If the "
        "results don't answer it, say so. Do not speculate. Do not change "
        "the user's in-progress data access request, if any."
    )
    answer = _synthesize(question, context, system_prompt=system_prompt)
    return {"messages": [AIMessage(content=answer)], "mode": "faq"}
