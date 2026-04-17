from __future__ import annotations

"""Tests for the routing classifiers.

Structured button-click payloads are dispatched deterministically and are
verified directly. Free-text classification is delegated to a gpt-4o
tool-calling LLM (see :mod:`app.graph.router_logic`); we stub that LLM with
a fake that returns canned ``tool_calls`` so tests stay deterministic and
offline.
"""

from typing import Any

import pytest

from app.graph import router_logic
from app.graph.router_logic import (
    classify_fresh_turn_text,
    classify_resume_value,
    classify_workflow_text,
    nav_intent_from_resume_value,
)
from app.graph.state import (
    RA_STEP_CHOOSE_ANONYMIZATION,
    RA_STEP_CHOOSE_DOMAIN,
    RA_STEP_CHOOSE_PRODUCTS,
)


# --------------------------------------------------------------------------- #
# Fake LLM                                                                    #
# --------------------------------------------------------------------------- #


class _FakeAIMessage:
    """Mimics the shape of a langchain ``AIMessage`` for tests."""

    def __init__(self, tool_calls: list[dict[str, Any]] | None) -> None:
        self.tool_calls = tool_calls or []
        self.content = ""
        self.type = "ai"


class _FakeLLM:
    """Returns a canned ``AIMessage`` mapped from the user's text."""

    def __init__(self, mapping: dict[str, dict[str, Any] | None]) -> None:
        self._mapping = mapping

    def invoke(self, messages: list[Any]) -> _FakeAIMessage:
        user_text = ""
        for m in reversed(messages):
            if getattr(m, "type", None) == "human":
                user_text = getattr(m, "content", "") or ""
                break
        # Match on a substring key for flexibility
        tc = None
        for needle, call in self._mapping.items():
            if needle.lower() in user_text.lower():
                tc = call
                break
        if tc is None:
            return _FakeAIMessage(tool_calls=[])
        return _FakeAIMessage(
            tool_calls=[{"name": tc["name"], "args": tc.get("args") or {}, "id": "tc"}]
        )


@pytest.fixture(autouse=True)
def _reset_llm_singletons() -> None:
    router_logic._fresh_llm = None
    router_logic._workflow_llm = None
    yield
    router_logic._fresh_llm = None
    router_logic._workflow_llm = None


def _install_workflow_llm(mapping: dict[str, dict[str, Any] | None]) -> None:
    router_logic._workflow_llm = _FakeLLM(mapping)


def _install_fresh_llm(mapping: dict[str, dict[str, Any] | None]) -> None:
    router_logic._fresh_llm = _FakeLLM(mapping)


# --------------------------------------------------------------------------- #
# Structured (non-LLM) dispatch                                               #
# --------------------------------------------------------------------------- #


def test_nav_intent_from_resume_value() -> None:
    assert nav_intent_from_resume_value({"action": "refine_filters"}) == RA_STEP_CHOOSE_DOMAIN
    assert nav_intent_from_resume_value({"action": "add_more"}) == RA_STEP_CHOOSE_PRODUCTS
    assert nav_intent_from_resume_value({"action": "change_selection"}) == RA_STEP_CHOOSE_PRODUCTS
    assert nav_intent_from_resume_value({"action": "view_cart"}) == "view_cart"
    assert nav_intent_from_resume_value({"action": "something_else"}) is None
    assert nav_intent_from_resume_value("not a dict") is None


def test_classify_resume_value_structured_paths_skip_llm() -> None:
    """Button-click payloads must never hit the LLM."""
    # Install an LLM that would raise if invoked
    class _RaisingLLM:
        def invoke(self, _messages: list[Any]) -> None:  # pragma: no cover
            raise AssertionError("LLM must not be called for structured payloads")

    router_logic._workflow_llm = _RaisingLLM()  # type: ignore[assignment]

    assert classify_resume_value({"facet": "domain", "value": "commercial"})["kind"] == "answer"
    assert classify_resume_value({"action": "select", "products": []})["kind"] == "answer"
    assert classify_resume_value({"action": "submit"})["kind"] == "answer"
    assert classify_resume_value({"action": "fill_forms"})["kind"] == "answer"
    assert classify_resume_value({"form_data": {"x": 1}})["kind"] == "answer"
    assert classify_resume_value({"action": "refine_filters"})["kind"] == "nav"
    assert classify_resume_value({"action": "add_more"})["kind"] == "nav"
    assert classify_resume_value(None)["kind"] == "unknown"


# --------------------------------------------------------------------------- #
# Workflow (paused-flow) text classifier                                      #
# --------------------------------------------------------------------------- #


def test_workflow_text_faq_kb() -> None:
    _install_workflow_llm({"ihd process": {"name": "ask_faq_kb", "args": {"question": "What is IHD?"}}})
    result = classify_workflow_text("Explain the IHD process please")
    assert result["kind"] == "faq"


def test_workflow_text_general_web() -> None:
    _install_workflow_llm(
        {"weather": {"name": "ask_general_web", "args": {"question": "today's weather"}}}
    )
    result = classify_workflow_text("What's the weather today?")
    assert result["kind"] == "general_web"


def test_workflow_text_navigate_to_step_domain() -> None:
    _install_workflow_llm(
        {"change domain": {"name": "navigate_to_step", "args": {"target": "choose_domain"}}}
    )
    result = classify_workflow_text("I want to change domain")
    assert result["kind"] == "nav"
    assert result["nav_target"] == RA_STEP_CHOOSE_DOMAIN


def test_workflow_text_navigate_to_anonymization() -> None:
    _install_workflow_llm(
        {
            "anonymization": {
                "name": "navigate_to_step",
                "args": {"target": "choose_anonymization"},
            }
        }
    )
    result = classify_workflow_text("change the anonymization level")
    assert result["kind"] == "nav"
    assert result["nav_target"] == RA_STEP_CHOOSE_ANONYMIZATION


def test_workflow_text_view_cart() -> None:
    _install_workflow_llm(
        {"show cart": {"name": "navigate_to_step", "args": {"target": "view_cart"}}}
    )
    result = classify_workflow_text("show cart please")
    assert result["kind"] == "nav"
    assert result["nav_target"] == "view_cart"


def test_workflow_text_resume() -> None:
    _install_workflow_llm({"continue": {"name": "resume_workflow", "args": {}}})
    result = classify_workflow_text("continue")
    assert result["kind"] == "resume"


def test_workflow_text_side_remark() -> None:
    _install_workflow_llm({"hello": {"name": "side_remark", "args": {}}})
    result = classify_workflow_text("hello there")
    assert result["kind"] == "side_text"


def test_workflow_text_no_tool_call_is_side_text() -> None:
    _install_workflow_llm({})  # LLM returns no tool call
    assert classify_workflow_text("xyz")["kind"] == "side_text"


# --------------------------------------------------------------------------- #
# Fresh-turn classifier                                                        #
# --------------------------------------------------------------------------- #


def test_fresh_turn_start_access() -> None:
    _install_fresh_llm(
        {
            "access": {
                "name": "start_access_request",
                "args": {"search_query": "clinical data"},
            }
        }
    )
    result = classify_fresh_turn_text("I need access to clinical data")
    assert result["kind"] == "start_access"
    assert result["search_query"] == "clinical data"


def test_fresh_turn_faq_kb() -> None:
    _install_fresh_llm(
        {"ihd": {"name": "faq_kb_question", "args": {"question": "what is IHD?"}}}
    )
    result = classify_fresh_turn_text("what is IHD?")
    assert result["kind"] == "faq_kb"


def test_fresh_turn_general_web() -> None:
    _install_fresh_llm(
        {"news": {"name": "general_web_question", "args": {"question": "latest news"}}}
    )
    result = classify_fresh_turn_text("latest news about AI")
    assert result["kind"] == "general_web"


def test_fresh_turn_status() -> None:
    _install_fresh_llm(
        {
            "status": {
                "name": "check_request_status",
                "args": {"request_id": "REQ-123"},
            }
        }
    )
    result = classify_fresh_turn_text("status of REQ-123")
    assert result["kind"] == "status_check"
    assert result["request_id"] == "REQ-123"


def test_fresh_turn_direct_when_no_tool_call() -> None:
    _install_fresh_llm({})
    result = classify_fresh_turn_text("??")
    assert result["kind"] == "direct"


# --------------------------------------------------------------------------- #
# classify_resume_value end-to-end (text goes through LLM)                    #
# --------------------------------------------------------------------------- #


def test_resume_value_user_message_routes_through_llm() -> None:
    _install_workflow_llm(
        {"ihd process": {"name": "ask_faq_kb", "args": {"question": "what is IHD?"}}}
    )
    result = classify_resume_value(
        {"action": "user_message", "text": "explain the IHD process"}
    )
    assert result["kind"] == "faq"
    assert result["text"] == "explain the IHD process"


def test_resume_value_bare_string_routes_through_llm() -> None:
    _install_workflow_llm(
        {"hi": {"name": "side_remark", "args": {}}}
    )
    result = classify_resume_value("hi")
    assert result["kind"] == "user_text"  # normalized from side_text
