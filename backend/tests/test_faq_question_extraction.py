from __future__ import annotations

"""Regression tests for :func:`app.graph.faq_agents._extract_question`.

The bug we guard against: on a *resume* turn, ``ChatService`` wraps the user's
text as ``Command(resume={"action":"user_message","text":…})`` instead of
appending a new ``HumanMessage``. If ``_extract_question`` falls through to
``last_human_message(state)`` it returns the oldest human text — typically
the original access-request search query — and the FAQ agent ends up
answering a stale question. The fix: prefer the routing-classifier's
most-recent tool-call ``question`` argument.
"""

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.faq_agents import _extract_question


def _tool_call(name: str, question: str) -> list[dict]:
    return [{"name": name, "args": {"question": question}, "id": "tc"}]


def test_extracts_from_subgraph_classifier_tool_call() -> None:
    state = {
        "messages": [
            HumanMessage(content="I need access to clinical telemetry data"),
            AIMessage(
                content="",
                tool_calls=_tool_call("ask_faq_kb", "What is IHD disclosure"),
            ),
        ],
        "last_resume_value": None,
    }
    assert _extract_question(state) == "What is IHD disclosure"


def test_extracts_from_parent_supervisor_tool_call() -> None:
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=_tool_call("faq_kb_question", "how does de-identification work"),
            ),
        ],
    }
    assert _extract_question(state) == "how does de-identification work"


def test_prefers_most_recent_tool_call_over_older() -> None:
    state = {
        "messages": [
            HumanMessage(content="I want access to data"),
            AIMessage(content="", tool_calls=_tool_call("ask_faq_kb", "old question")),
            AIMessage(content="old FAQ answer"),
            HumanMessage(content="follow-up"),
            AIMessage(content="", tool_calls=_tool_call("ask_faq_kb", "new question")),
        ],
    }
    assert _extract_question(state) == "new question"


def test_ignores_older_tool_calls_when_latest_ai_has_no_faq_tool() -> None:
    """An AIMessage without a FAQ tool-call must not let older tool-calls leak."""
    state = {
        "messages": [
            AIMessage(content="", tool_calls=_tool_call("ask_faq_kb", "stale")),
            AIMessage(content="an answer"),
            HumanMessage(content="fresh text"),
            AIMessage(content="", tool_calls=[{"name": "other_tool", "args": {}, "id": "x"}]),
        ],
        "last_resume_value": None,
    }
    # Falls back to resume value or last human message, NOT the stale tool-call
    assert _extract_question(state) == "fresh text"


def test_falls_back_to_last_resume_value() -> None:
    state = {
        "messages": [
            HumanMessage(content="original request"),
        ],
        "last_resume_value": {
            "action": "user_message",
            "text": "What is IHD disclosure",
        },
    }
    assert _extract_question(state) == "What is IHD disclosure"


def test_falls_back_to_last_human_message() -> None:
    state = {
        "messages": [
            HumanMessage(content="first"),
            AIMessage(content="reply"),
            HumanMessage(content="second"),
        ],
    }
    assert _extract_question(state) == "second"


def test_accepts_search_query_arg_for_fresh_turn_tool() -> None:
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "general_web_question",
                        "args": {"question": "weather today"},
                        "id": "tc",
                    }
                ],
            ),
        ],
    }
    assert _extract_question(state) == "weather today"
