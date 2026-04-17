from __future__ import annotations

"""End-to-end simulation that reproduces the user's bug:

> User in a paused request-access workflow types "lets continue" (classifier
> -> resume_workflow), workflow redisplays the step, then user types
> "what is disclosure in IHD Process" (classifier -> ask_faq_kb). The FAQ
> agent must receive *"what is disclosure in IHD Process"* as the question —
> NOT the previous "lets continue".

Both the parent and subgraph graphs are built for real; the routing LLM and
the FAQ service are the only mocks. If the fix works, the FAQ service is
called with the current question. If the bug is still present, it's called
with a stale one.
"""

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


def _ainvoke(graph: Any, payload: Any, cfg: dict) -> Any:
    """Run ``graph.ainvoke`` in a fresh event loop (subgraph nodes are async)."""
    return asyncio.run(graph.ainvoke(payload, cfg))

import app.graph.router_logic as _router_logic
import app.graph.subgraphs.request_access.nodes.extract_search_intent as _extract_mod
import app.graph.subgraphs.request_access.nodes.mcp_prefetch as _prefetch_mod
import app.graph.subgraphs.request_access.nodes.steps as _steps_mod
from app.graph.faq_agents import _extract_question, faq_kb_agent, general_faq_tavily_agent
from app.graph.parent_supervisor import recover_state_node, supervisor_router
from app.graph.state import AppState
from app.graph.subgraphs.request_access import build_request_access_subgraph

from langgraph.types import Command


# --------------------------------------------------------------------------- #
# LLM + service stubs                                                         #
# --------------------------------------------------------------------------- #


def _ai_with_tool(name: str, args: dict[str, Any]) -> AIMessage:
    # The routers now require a ``confidence`` arg on every tool call. For
    # simulation purposes we always report high confidence so the router
    # dispatches instead of asking for clarification.
    args_with_conf = {**args}
    args_with_conf.setdefault("confidence", 0.95)
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args_with_conf, "id": f"tc_{name}"}],
    )


class _ScriptedLLM:
    """LLM stub that returns canned responses keyed by the user text.

    ``mapping`` is a list of ``(substring, AIMessage)`` pairs; the first
    substring that matches (case-insensitive) in the latest HumanMessage's
    content wins. If none match, an AIMessage with no tool_calls is returned.
    """

    def __init__(self, mapping: list[tuple[str, AIMessage]]) -> None:
        self._mapping = mapping
        self.invocations: list[str] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        text = ""
        for m in reversed(messages):
            if getattr(m, "type", None) == "human":
                text = (getattr(m, "content", "") or "")
                break
        self.invocations.append(text)
        low = text.lower()
        for needle, response in self._mapping:
            if needle.lower() in low:
                return response
        return AIMessage(content="", tool_calls=[])


class _CapturingFaqService:
    """Fake FaqService that records every question it was asked."""

    def __init__(self) -> None:
        self.questions: list[str] = []

    def search(self, q: str) -> list[dict]:
        self.questions.append(q)
        return [{"url": "http://example/kb", "content": f"KB content for: {q}"}]


# --------------------------------------------------------------------------- #
# Test harness                                                                #
# --------------------------------------------------------------------------- #


_PATCHED = False


def _patch_products_search() -> None:
    global _PATCHED
    if _PATCHED:
        return

    async def _fake_search(**_: Any) -> list[dict]:
        return [
            {
                "content": "Mock product",
                "metadata": {
                    "id": "dp-mock",
                    "domain": "commercial",
                    "product_type": "default",
                    "sensitivity": "low",
                },
                "score": 1.0,
            }
        ]

    _steps_mod.build_search_products_query = _fake_search  # type: ignore[assignment]

    _extract_mod.extract_search_intent = lambda text: {  # type: ignore[assignment]
        "search_text": (text or "").strip() or "*",
        "study_id": "",
    }

    async def _no_facets() -> dict:
        return {}

    _prefetch_mod.mcp_search_client.list_facets = _no_facets  # type: ignore[attr-defined]

    _PATCHED = True


def _install_workflow_llm() -> _ScriptedLLM:
    """Configure the workflow-text classifier to reproduce the user flow."""
    llm = _ScriptedLLM(
        [
            # "lets continue" -> resume_workflow
            ("lets continue", _ai_with_tool("resume_workflow", {})),
            ("continue", _ai_with_tool("resume_workflow", {})),
            # The actual FAQ question
            (
                "disclosure",
                _ai_with_tool(
                    "ask_faq_kb", {"question": "what is disclosure in IHD Process"}
                ),
            ),
            # Any generic "explain" text for other tests
            ("explain", _ai_with_tool("ask_faq_kb", {"question": "explain"})),
        ]
    )
    _router_logic._workflow_llm = llm  # type: ignore[assignment]
    _router_logic._fresh_llm = llm  # type: ignore[assignment]
    return llm


def _install_faq_llm(response_text: str = "(kb answer)") -> None:
    """The ``faq_kb_agent`` synthesises a final answer via ``get_chat_llm()``.

    Patch that factory so it returns a deterministic message.
    """

    class _FaqLLM:
        def invoke(self, _prompt: list[Any]) -> AIMessage:
            return AIMessage(content=response_text)

    import app.graph.faq_agents as _faq_mod

    _faq_mod.get_chat_llm = lambda: _FaqLLM()  # type: ignore[assignment]


def _install_faq_service() -> _CapturingFaqService:
    svc = _CapturingFaqService()
    import app.graph.faq_agents as _faq_mod

    _faq_mod._faq_service = lambda: svc  # type: ignore[assignment]
    return svc


def _stub_status(state: AppState) -> dict:
    return {"messages": [AIMessage(content="(status)")]}


def _build_full_graph(faq_spy: Any | None = None) -> Any:
    """Build parent graph with real supervisor + real subgraph, in-memory ckpt."""
    _patch_products_search()
    ra_sub = build_request_access_subgraph()

    b = StateGraph(AppState)
    b.add_node("recover_state", recover_state_node)
    b.add_node("supervisor_router", supervisor_router)
    b.add_node("request_access_subgraph", ra_sub)
    b.add_node("faq_kb_agent", faq_spy or faq_kb_agent)
    b.add_node("general_faq_tavily_agent", general_faq_tavily_agent)
    b.add_node("status_agent", _stub_status)

    b.add_edge(START, "recover_state")
    b.add_edge("recover_state", "supervisor_router")
    b.add_edge("request_access_subgraph", END)
    b.add_edge("faq_kb_agent", END)
    b.add_edge("general_faq_tavily_agent", END)
    b.add_edge("status_agent", END)
    return b.compile(checkpointer=InMemorySaver())


def _pending_interrupt(graph: Any, cfg: dict) -> dict | None:
    s = graph.get_state(cfg, subgraphs=True)
    for task in s.tasks:
        if task.interrupts:
            return task.interrupts[0].value
        if task.state and task.state.tasks:
            for sub in task.state.tasks:
                if sub.interrupts:
                    return sub.interrupts[0].value
    return None


# --------------------------------------------------------------------------- #
# Regression simulation                                                       #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset() -> None:
    _router_logic._workflow_llm = None
    _router_logic._fresh_llm = None
    yield
    _router_logic._workflow_llm = None
    _router_logic._fresh_llm = None


def test_faq_after_resume_uses_current_question_not_previous() -> None:
    """Reproduces the exact user-reported bug flow.

    1. Start a request (subgraph pauses on choose_domain).
    2. Resume with ``facet=domain/value=commercial`` (structured, no LLM).
    3. Resume with ``facet=anonymization/value=deidentified`` (structured).
    4. Now we're paused on ``choose_products``.
    5. Send free text "lets continue" (LLM -> resume_workflow).
       → workflow redisplays the choose_products step.
    6. Send free text "what is disclosure in IHD Process"
       (LLM -> ask_faq_kb with question="what is disclosure in IHD Process").
       → must hand off to faq_kb_agent with the CURRENT question.
    """
    _install_workflow_llm()
    _install_faq_llm()
    svc = _install_faq_service()

    g = _build_full_graph()
    cfg = {"configurable": {"thread_id": "sim-faq-1"}}

    # Fresh start
    _ainvoke(g, 
        {
            "messages": [],
            "thread_id": "sim-faq-1",
            "user_id": "u",
            "active_flow": "request_access",
            "ra_search_query": "I need access to some data",
        },
        cfg,
    )
    # We should be paused on choose_domain
    assert _pending_interrupt(g, cfg) is not None

    # Structured resumes past domain + anonymization (no LLM)
    _ainvoke(g, Command(resume={"facet": "domain", "value": "commercial"}), cfg)
    _ainvoke(g, Command(resume={"facet": "anonymization", "value": "deidentified"}), cfg)

    # Paused on choose_products now
    val = _pending_interrupt(g, cfg)
    assert val is not None
    assert val["type"] == "product_selection"

    # Step 5: "lets continue" -> resume_workflow -> redisplays choose_products
    _ainvoke(g, Command(resume={"action": "user_message", "text": "lets continue"}), cfg)
    # Still paused on choose_products after resume_workflow
    val = _pending_interrupt(g, cfg)
    assert val is not None
    assert val["type"] == "product_selection"

    # Step 6: the actual FAQ question
    _ainvoke(g, 
        Command(
            resume={
                "action": "user_message",
                "text": "what is disclosure in IHD Process",
            }
        ),
        cfg,
    )

    # The FAQ service must have been asked the CURRENT question, not "continue"
    assert svc.questions, "faq_kb_agent was never called"
    last_q = svc.questions[-1]
    assert "disclosure" in last_q.lower(), (
        f"faq_kb_agent received stale question {last_q!r}; expected the current"
        f" 'what is disclosure in IHD Process'. All questions: {svc.questions}"
    )
    # Specifically, it must not have been the previous user text
    assert "continue" not in last_q.lower(), (
        f"faq_kb_agent got a stale 'continue'-related question: {last_q!r}"
    )


def test_extract_question_from_live_state_after_handoff() -> None:
    """Same flow as above but asserts ``_extract_question`` directly against
    the parent's ``state`` dict right before ``faq_kb_agent`` synthesises.

    This pin-points whether the classifier's AIMessage reaches parent state.
    """
    _install_workflow_llm()
    _install_faq_llm()
    svc = _install_faq_service()

    captured_states: list[dict] = []

    import app.graph.faq_agents as _faq_mod

    real = _faq_mod.faq_kb_agent

    def _spy(state: AppState) -> dict:
        captured_states.append(dict(state))
        return real(state)

    g = _build_full_graph(faq_spy=_spy)

    cfg = {"configurable": {"thread_id": "sim-faq-2"}}
    _ainvoke(g, 
        {
            "messages": [],
            "thread_id": "sim-faq-2",
            "user_id": "u",
            "active_flow": "request_access",
            "ra_search_query": "need access",
        },
        cfg,
    )
    _ainvoke(g, Command(resume={"facet": "domain", "value": "commercial"}), cfg)
    _ainvoke(g, Command(resume={"facet": "anonymization", "value": "deidentified"}), cfg)
    _ainvoke(g, Command(resume={"action": "user_message", "text": "lets continue"}), cfg)
    _ainvoke(g, 
        Command(
            resume={
                "action": "user_message",
                "text": "what is disclosure in IHD Process",
            }
        ),
        cfg,
    )

    assert captured_states, "faq_kb_agent was never reached"
    state = captured_states[-1]

    q = _extract_question(state)
    assert "disclosure" in q.lower(), (
        f"_extract_question returned stale {q!r}. "
        f"state.messages={[(type(m).__name__, getattr(m, 'tool_calls', None), getattr(m, 'content', '')[:40]) for m in state.get('messages', [])]} "
        f"last_resume_value={state.get('last_resume_value')!r}"
    )
