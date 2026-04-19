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
    CONFIDENCE_THRESHOLD,
    build_clarify_message,
    classify_fresh_turn_text,
    classify_resume_value,
    classify_workflow_text,
    classify_yes_no,
    nav_intent_from_resume_value,
)
from app.graph.state import (
    RA_STEP_CHOOSE_ANONYMIZATION,
    RA_STEP_CHOOSE_DOMAIN,
    RA_STEP_NARROW_SEARCH,
    RA_STEP_CHOOSE_PRODUCTS,
)


# --------------------------------------------------------------------------- #
# Fake LLM                                                                    #
# --------------------------------------------------------------------------- #

# Default confidence used in tests unless a test explicitly overrides it.
_CONFIDENT = 0.95
_UNCERTAIN = 0.6


class _FakeAIMessage:
    """Mimics the shape of a langchain ``AIMessage`` for tests."""

    def __init__(self, tool_calls: list[dict[str, Any]] | None) -> None:
        self.tool_calls = tool_calls or []
        self.content = ""
        self.type = "ai"


class _FakeLLM:
    """Returns a canned ``AIMessage`` mapped from the user's text.

    Each mapping value is the tool-call dict. If it doesn't set
    ``args.confidence``, the fake injects ``_CONFIDENT`` so the router
    dispatches instead of asking for clarification.
    """

    def __init__(self, mapping: dict[str, dict[str, Any] | None]) -> None:
        self._mapping = mapping

    def invoke(self, messages: list[Any]) -> _FakeAIMessage:
        user_text = ""
        for m in reversed(messages):
            if getattr(m, "type", None) == "human":
                user_text = getattr(m, "content", "") or ""
                break
        tc = None
        for needle, call in self._mapping.items():
            if needle.lower() in user_text.lower():
                tc = call
                break
        if tc is None:
            return _FakeAIMessage(tool_calls=[])
        args = dict(tc.get("args") or {})
        args.setdefault("confidence", _CONFIDENT)
        return _FakeAIMessage(
            tool_calls=[{"name": tc["name"], "args": args, "id": "tc"}]
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
    assert nav_intent_from_resume_value({"action": "refine_filters"}) == RA_STEP_NARROW_SEARCH
    assert nav_intent_from_resume_value({"action": "add_more"}) == RA_STEP_CHOOSE_PRODUCTS
    assert nav_intent_from_resume_value({"action": "change_selection"}) == RA_STEP_CHOOSE_PRODUCTS
    assert nav_intent_from_resume_value({"action": "view_cart"}) == "view_cart"
    assert nav_intent_from_resume_value({"action": "something_else"}) is None
    assert nav_intent_from_resume_value("not a dict") is None


def test_classify_resume_value_structured_paths_skip_llm() -> None:
    """Button-click payloads must never hit the LLM."""
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
    assert result["confidence"] >= CONFIDENCE_THRESHOLD


def test_workflow_text_navigate_to_step_domain() -> None:
    """Textual "change domain" intents now route to the narrowing subagent,
    not the legacy chip picker.
    """
    _install_workflow_llm(
        {"change domain": {"name": "navigate_to_step", "args": {"target": "choose_domain"}}}
    )
    result = classify_workflow_text("I want to change domain")
    assert result["kind"] == "nav"
    assert result["nav_target"] == RA_STEP_NARROW_SEARCH


def test_workflow_text_navigate_to_anonymization() -> None:
    """Likewise, "change anonymization" goes through ``narrow_search`` — the
    user can keep typing plain text to refine their filters.
    """
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
    assert result["nav_target"] == RA_STEP_NARROW_SEARCH


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


def test_workflow_text_out_of_scope() -> None:
    _install_workflow_llm(
        {"weather": {"name": "out_of_scope_workflow", "args": {"reason": "weather"}}}
    )
    result = classify_workflow_text("what's the weather today?")
    assert result["kind"] == "out_of_scope"
    assert result.get("reason") == "weather"


def test_workflow_text_low_confidence_becomes_clarify() -> None:
    """faq/nav/resume at <0.9 confidence are re-labelled as clarify."""
    _install_workflow_llm(
        {
            "maybe": {
                "name": "ask_faq_kb",
                "args": {"question": "…", "confidence": _UNCERTAIN},
            }
        }
    )
    result = classify_workflow_text("maybe something about IHD?")
    assert result["kind"] == "clarify"
    assert result["candidate_kind"] == "faq"
    assert result["confidence"] == pytest.approx(_UNCERTAIN)


def test_workflow_text_low_confidence_side_text_not_clarified() -> None:
    """side_text and out_of_scope are NOT re-labelled to clarify."""
    _install_workflow_llm(
        {
            "hmm": {
                "name": "side_remark",
                "args": {"confidence": _UNCERTAIN},
            }
        }
    )
    result = classify_workflow_text("hmm")
    assert result["kind"] == "side_text"


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
    assert result["confidence"] >= CONFIDENCE_THRESHOLD


def test_fresh_turn_faq_kb() -> None:
    _install_fresh_llm(
        {"ihd": {"name": "faq_kb_question", "args": {"question": "what is IHD?"}}}
    )
    result = classify_fresh_turn_text("what is IHD?")
    assert result["kind"] == "faq_kb"


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


def test_fresh_turn_out_of_scope() -> None:
    _install_fresh_llm(
        {
            "weather": {
                "name": "out_of_scope",
                "args": {"reason": "weather question"},
            }
        }
    )
    result = classify_fresh_turn_text("what's the weather today?")
    assert result["kind"] == "out_of_scope"
    assert result.get("reason") == "weather question"


def test_fresh_turn_low_confidence_becomes_clarify() -> None:
    _install_fresh_llm(
        {
            "maybe": {
                "name": "start_access_request",
                "args": {"search_query": "x", "confidence": _UNCERTAIN},
            }
        }
    )
    result = classify_fresh_turn_text("maybe some data")
    assert result["kind"] == "clarify"
    assert result["candidate_kind"] == "start_access"
    assert result["confidence"] == pytest.approx(_UNCERTAIN)


def test_fresh_turn_out_of_scope_bypasses_confidence_check() -> None:
    """Even low-confidence out_of_scope is honored (no clarify override)."""
    _install_fresh_llm(
        {
            "weather": {
                "name": "out_of_scope",
                "args": {"reason": "weather", "confidence": _UNCERTAIN},
            }
        }
    )
    result = classify_fresh_turn_text("weather")
    assert result["kind"] == "out_of_scope"


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


def test_resume_value_out_of_scope_passthrough() -> None:
    _install_workflow_llm(
        {
            "weather": {
                "name": "out_of_scope_workflow",
                "args": {"reason": "weather"},
            }
        }
    )
    result = classify_resume_value(
        {"action": "user_message", "text": "what's the weather today?"}
    )
    assert result["kind"] == "out_of_scope"
    assert result["text"] == "what's the weather today?"


# --------------------------------------------------------------------------- #
# build_clarify_message                                                       #
# --------------------------------------------------------------------------- #


def test_clarify_message_start_access_with_query() -> None:
    msg = build_clarify_message(
        {"candidate_kind": "start_access", "search_query": "commercial data"}
    )
    assert "request access" in msg.lower()
    assert "commercial data" in msg
    assert "yes" in msg.lower()


def test_clarify_message_start_access_without_query() -> None:
    msg = build_clarify_message({"candidate_kind": "start_access"})
    assert "request access" in msg.lower()
    assert "yes" in msg.lower()


def test_clarify_message_faq_with_question() -> None:
    msg = build_clarify_message(
        {
            "candidate_kind": "faq_kb",
            "tool_call": {"args": {"question": "what is IHD?"}},
        }
    )
    assert "ihd process" in msg.lower()
    assert "what is IHD?" in msg


def test_clarify_message_status_with_request_id() -> None:
    msg = build_clarify_message(
        {"candidate_kind": "status_check", "request_id": "REQ-77"}
    )
    assert "REQ-77" in msg
    assert "status" in msg.lower()


def test_clarify_message_nav_targets() -> None:
    msg = build_clarify_message(
        {"candidate_kind": "nav", "nav_target": "choose_domain"}
    )
    assert "data domain" in msg.lower()


def test_clarify_message_generic_fallback_in_workflow() -> None:
    msg = build_clarify_message({}, in_workflow=True)
    assert "ihd process" in msg.lower()
    assert "paused" in msg.lower()


# --------------------------------------------------------------------------- #
# classify_yes_no                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text", ["yes", "Yes", "YES!", "yeah", "yep", "sure", "correct", "ok", "okay", "proceed"])
def test_classify_yes_no_affirmative(text: str) -> None:
    assert classify_yes_no(text) == "yes"


@pytest.mark.parametrize("text", ["no", "No.", "nope", "nah", "cancel", "never mind", "wrong"])
def test_classify_yes_no_negative(text: str) -> None:
    assert classify_yes_no(text) == "no"


@pytest.mark.parametrize(
    "text",
    ["yes but also something else", "I need data", "maybe", "", "    ", "ok please help me with X"],
)
def test_classify_yes_no_falls_through(text: str) -> None:
    assert classify_yes_no(text) is None


def test_resume_value_clarify_passthrough() -> None:
    _install_workflow_llm(
        {
            "maybe": {
                "name": "ask_faq_kb",
                "args": {"question": "…", "confidence": _UNCERTAIN},
            }
        }
    )
    result = classify_resume_value(
        {"action": "user_message", "text": "maybe something?"}
    )
    assert result["kind"] == "clarify"
    assert result["candidate_kind"] == "faq"
