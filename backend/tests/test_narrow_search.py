"""Unit tests for the request-access narrowing subagent.

The agent runs a small ReAct-style loop using two tools (``ask_user`` /
``commit_narrow``). These tests stub the LLM so the loop is fully
deterministic and exercise:

  * fresh entry → LLM commits immediately → handoff to ``search_products``
  * fresh entry → LLM asks the user → ``narrow_message`` interrupt
  * resume after an ``ask_user`` → LLM commits with the user's answer
  * defensive turn cap → force-commit
  * malformed LLM response → force-commit (never hangs)
  * ``commit_narrow`` with study id → propagated through to state
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from app.graph.state import (
    RA_STEP_NARROW_SEARCH,
    RA_STEP_SEARCH_PRODUCTS,
)
from app.graph.subgraphs.request_access.nodes import narrow_search as narrow_mod


class _StubInterrupt(Exception):
    """Replaces ``langgraph.types.interrupt`` in tests so we can assert on
    the payload without standing up a full runnable context.
    """

    def __init__(self, payload: dict) -> None:
        super().__init__("stub interrupt")
        self.payload = payload


def _ai_with_tool_calls(name: str, args: dict, *, tc_id: str = "tc1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": tc_id, "type": "tool_call"}],
    )


class _FakeLLM:
    """Records ``ainvoke`` calls and returns scripted responses in order."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.calls: list[list[Any]] = []

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        self.calls.append(list(messages))
        if not self.responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self.responses.pop(0)


def _patch_llm(responses: list[AIMessage]) -> _FakeLLM:
    fake = _FakeLLM(responses)
    # ``narrow_search`` lazily builds the bound LLM in ``_get_llm``. Reset the
    # module-level cache and patch the factory so the next call returns our
    # stub regardless of which test ran first.
    narrow_mod._llm = None
    return fake


# ---------------------------------------------------------------------------
# Happy path: commit immediately
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_pass_commits_and_handoffs_to_search() -> None:
    fake = _patch_llm(
        [
            _ai_with_tool_calls(
                "commit_narrow",
                {
                    "search_text": "diabetes labs",
                    "domain": "clinical",
                    "anonymization": "deidentified",
                    "study_id": "dp-501",
                },
            )
        ]
    )

    state: dict = {
        "ra_search_query": "diabetes labs for dp-501",
        "mcp_facet_cache": {
            "domains": [{"id": "clinical", "label": "Clinical"}],
            "anonymization": [{"id": "deidentified", "label": "De-identified"}],
        },
    }

    with patch.object(narrow_mod, "_get_llm", return_value=fake):
        cmd = await narrow_mod.narrow_search(state)  # type: ignore[arg-type]

    assert cmd.goto == "search_products"
    assert cmd.update["current_step"] == RA_STEP_SEARCH_PRODUCTS
    assert cmd.update["narrow_state"] is None  # cleared on commit
    assert cmd.update["ra_search_query"] == "diabetes labs"
    assert cmd.update["ra_study_id"] == "dp-501"
    assert cmd.update["selected_anonymization"] == "deidentified"
    assert cmd.update["selected_domains"] == ["clinical"]


# ---------------------------------------------------------------------------
# ask_user → interrupt with a narrow_message payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_user_emits_narrow_message_interrupt() -> None:
    fake = _patch_llm(
        [
            _ai_with_tool_calls(
                "ask_user",
                {"message": "What domain should I search in?"},
                tc_id="tc-q1",
            )
        ]
    )
    state: dict = {"ra_search_query": "patient demographics", "mcp_facet_cache": {}}

    def _stub_interrupt(payload: dict) -> None:
        raise _StubInterrupt(payload)

    with patch.object(narrow_mod, "_get_llm", return_value=fake), patch.object(
        narrow_mod, "interrupt", _stub_interrupt
    ):
        with pytest.raises(_StubInterrupt) as excinfo:
            await narrow_mod.narrow_search(state)  # type: ignore[arg-type]

    payload = excinfo.value.payload
    assert payload["type"] == "narrow_message"
    assert payload["message"] == "What domain should I search in?"
    assert payload["step"] == RA_STEP_NARROW_SEARCH
    assert "prompt_id" in payload


# ---------------------------------------------------------------------------
# Resume path: previous ask_user is folded into the transcript and the LLM
# can then commit on the next iteration.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_appends_tool_message_then_commits() -> None:
    # Pretend the agent already asked once last turn.
    seeded_messages = [
        AIMessage(content="seed-system"),
        _ai_with_tool_calls(
            "ask_user", {"message": "anonymization?"}, tc_id="tc-q1"
        ),
    ]
    state: dict = {
        "ra_search_query": "diabetes",
        "ra_study_id": "dp-501",
        "mcp_facet_cache": {},
        "narrow_state": {
            "messages": seeded_messages,
            "turns": 1,
            "pending_tc_id": "tc-q1",
        },
        "last_resume_value": {"action": "user_message", "text": "deidentified"},
    }

    fake = _patch_llm(
        [
            _ai_with_tool_calls(
                "commit_narrow",
                {
                    "search_text": "diabetes",
                    "domain": "",
                    "anonymization": "deidentified",
                    "study_id": "dp-501",
                },
            )
        ]
    )

    with patch.object(narrow_mod, "_get_llm", return_value=fake):
        cmd = await narrow_mod.narrow_search(state)  # type: ignore[arg-type]

    # The reply was folded into the LLM input as a ToolMessage.
    sent_msgs = fake.calls[0]
    tool_messages = [
        m for m in sent_msgs if getattr(m, "type", None) == "tool"
    ]
    assert len(tool_messages) == 1
    assert tool_messages[0].content == "deidentified"
    assert tool_messages[0].tool_call_id == "tc-q1"

    # And the commit landed correctly.
    assert cmd.goto == "search_products"
    assert cmd.update["selected_anonymization"] == "deidentified"
    assert cmd.update["narrow_state"] is None


# ---------------------------------------------------------------------------
# Defensive cap: the agent must never trap the user in an infinite loop.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_cap_force_commits_without_calling_llm() -> None:
    fake = _patch_llm([])  # empty — must not be invoked
    state: dict = {
        "ra_search_query": "anything",
        "narrow_state": {
            "messages": [],
            "turns": narrow_mod._MAX_TURNS,
            "pending_tc_id": None,
        },
    }

    with patch.object(narrow_mod, "_get_llm", return_value=fake):
        cmd = await narrow_mod.narrow_search(state)  # type: ignore[arg-type]

    assert cmd.goto == "search_products"
    assert cmd.update["narrow_state"] is None
    assert fake.calls == []


# ---------------------------------------------------------------------------
# Defensive: LLM returns plain text → commit with what we have, never hang.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_tool_call_force_commits() -> None:
    fake = _patch_llm([AIMessage(content="just talking, no tool")])
    state: dict = {"ra_search_query": "labs", "mcp_facet_cache": {}}

    with patch.object(narrow_mod, "_get_llm", return_value=fake):
        cmd = await narrow_mod.narrow_search(state)  # type: ignore[arg-type]

    assert cmd.goto == "search_products"
    assert cmd.update["ra_search_query"] == "labs"
    assert cmd.update["narrow_state"] is None


# ---------------------------------------------------------------------------
# Smoke: helper that pulls user text out of resume payloads
# ---------------------------------------------------------------------------


def test_extract_user_reply_handles_common_shapes() -> None:
    assert narrow_mod._extract_user_reply(None) == ""
    assert narrow_mod._extract_user_reply("hi") == "hi"
    assert (
        narrow_mod._extract_user_reply({"action": "user_message", "text": "hi"})
        == "hi"
    )
    # Non-text dict falls back to its repr — never raises.
    assert "foo" in narrow_mod._extract_user_reply({"foo": "bar"})


def test_extract_user_reply_runs_in_event_loop() -> None:
    # Sanity check that the helper is sync (no accidental coroutine).
    assert asyncio.iscoroutinefunction(narrow_mod._extract_user_reply) is False
