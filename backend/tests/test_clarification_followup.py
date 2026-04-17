from __future__ import annotations

"""Supervisor follow-up after a "Did you mean…?" clarification.

On turn N the classifier had low confidence and the supervisor emitted a
clarify message plus ``pending_clarification`` in state. On turn N+1 the
user replies with a simple affirmation ("yes" / "sure" / "ok") — the
supervisor must re-dispatch to the saved candidate intent rather than
re-running the LLM (where a bare "yes" would be classified as out_of_scope).
"""

from typing import Any

import pytest
from langchain_core.messages import HumanMessage

import app.graph.router_logic as _router_logic
from app.graph.parent_supervisor import supervisor_router


class _ShouldNotBeCalledLLM:
    """If the yes-path short-circuits correctly, the classifier is not
    invoked. This stub raises if the supervisor falls through to it."""

    def invoke(self, _messages: list[Any]) -> Any:  # pragma: no cover
        raise AssertionError(
            "classifier LLM should NOT be called when pending_clarification is confirmed"
        )


@pytest.fixture(autouse=True)
def _reset_llms() -> None:
    _router_logic._fresh_llm = None
    _router_logic._workflow_llm = None
    yield
    _router_logic._fresh_llm = None
    _router_logic._workflow_llm = None


def _state_with_pc(text: str, pc: dict) -> dict:
    return {
        "messages": [HumanMessage(content=text)],
        "pending_clarification": pc,
        "active_flow": "none",
    }


def test_yes_confirms_start_access_candidate() -> None:
    _router_logic._fresh_llm = _ShouldNotBeCalledLLM()  # type: ignore[assignment]
    state = _state_with_pc(
        "yes",
        {"candidate_kind": "start_access", "search_query": "data products"},
    )
    cmd = supervisor_router(state)
    assert cmd.goto == "request_access_subgraph"
    assert cmd.update["active_flow"] == "request_access"
    assert cmd.update["ra_search_query"] == "data products"
    assert cmd.update["pending_clarification"] is None


def test_yes_confirms_faq_candidate() -> None:
    _router_logic._fresh_llm = _ShouldNotBeCalledLLM()  # type: ignore[assignment]
    state = _state_with_pc("sure", {"candidate_kind": "faq_kb"})
    cmd = supervisor_router(state)
    assert cmd.goto == "faq_kb_agent"
    assert cmd.update["active_intent"] == "faq"
    assert cmd.update["pending_clarification"] is None


def test_yes_confirms_status_candidate() -> None:
    _router_logic._fresh_llm = _ShouldNotBeCalledLLM()  # type: ignore[assignment]
    state = _state_with_pc(
        "yep",
        {"candidate_kind": "status_check", "request_id": "REQ-99"},
    )
    cmd = supervisor_router(state)
    assert cmd.goto == "status_agent"
    assert cmd.update["last_request_id"] == "REQ-99"


def test_no_declines_and_clears() -> None:
    _router_logic._fresh_llm = _ShouldNotBeCalledLLM()  # type: ignore[assignment]
    state = _state_with_pc("no", {"candidate_kind": "start_access"})
    result = supervisor_router(state)
    # Returned as a dict (direct reply, no goto)
    assert isinstance(result, dict)
    assert result["supervisor_decision"] == "clarify_declined"
    assert result["pending_clarification"] is None
    # The assistant message was emitted
    msgs = result["messages"]
    assert any("what would you like" in getattr(m, "content", "").lower() for m in msgs)


def test_non_yes_non_no_falls_through_to_classifier() -> None:
    """If the user rephrases instead of yes/no, the classifier is invoked
    and the pending_clarification is implicitly cleared by the dispatch."""
    from langchain_core.messages import AIMessage

    class _ClassifyLLM:
        def invoke(self, _messages: list[Any]) -> Any:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "faq_kb_question",
                        "args": {"question": "explain IHD", "confidence": 0.95},
                        "id": "tc",
                    }
                ],
            )

    _router_logic._fresh_llm = _ClassifyLLM()  # type: ignore[assignment]
    state = _state_with_pc(
        "actually tell me about IHD",
        {"candidate_kind": "start_access", "search_query": "data"},
    )
    cmd = supervisor_router(state)
    assert cmd.goto == "faq_kb_agent"
    # Successful dispatch clears pending_clarification.
    assert cmd.update["pending_clarification"] is None
