from __future__ import annotations

"""End-to-end exercise of the request-access subgraph using an in-memory
checkpointer. Exercises: entry interrupt, resume with facet answer, navigation
invalidation, and FAQ handoff to the parent via Command.PARENT.

No database, LLM, or ChromaDB dependencies: ``search_products`` is patched to
return a small fixed product list so we don't hit OpenAI embeddings.
"""

import asyncio
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command


def _ainvoke(graph: Any, payload: Any, cfg: dict) -> Any:
    """Synchronous shim around ``graph.ainvoke`` for tests.

    Subgraph nodes like ``search_products`` and ``mcp_prefetch_facets`` are
    async (they call the MCP client), so LangGraph rejects the sync
    ``.invoke`` path. Each call runs in a fresh event loop to match the
    isolation of the previous sync tests.
    """
    return asyncio.run(graph.ainvoke(payload, cfg))

import app.graph.router_logic as _router_logic
import app.graph.subgraphs.request_access.nodes.extract_search_intent as _extract_mod
import app.graph.subgraphs.request_access.nodes.mcp_prefetch as _prefetch_mod
import app.graph.subgraphs.request_access.nodes.narrow_search as _narrow_mod
import app.graph.subgraphs.request_access.nodes.steps as _steps_mod
from app.graph.subgraphs.request_access import build_request_access_subgraph
from app.graph.state import AppState, RA_STEP_CHOOSE_DOMAIN, RA_STEP_NARROW_SEARCH


def _stub_ai_message(tool_calls: list[dict[str, Any]] | None = None) -> AIMessage:
    return AIMessage(content="", tool_calls=tool_calls or [])


class _StubWorkflowLLM:
    """Fake LLM that classifies free-text resume values deterministically.

    Matches by substring on the latest HumanMessage content; callers can
    extend ``_MAPPING`` if they add new text-bearing assertions.
    """

    _MAPPING: list[tuple[str, dict[str, Any]]] = [
        ("change domain", {"name": "navigate_to_step", "args": {"target": "choose_domain"}}),
        ("ihd process", {"name": "ask_faq_kb", "args": {"question": "IHD"}}),
        ("hello", {"name": "side_remark", "args": {}}),
    ]

    def invoke(self, messages: list[Any]) -> AIMessage:
        text = ""
        for m in reversed(messages):
            if getattr(m, "type", None) == "human":
                text = (getattr(m, "content", "") or "").lower()
                break
        for needle, call in self._MAPPING:
            if needle in text:
                # The router now requires ``confidence`` on every tool call.
                # Inject a high value so dispatching happens instead of
                # clarify.
                args = {**call["args"]}
                args.setdefault("confidence", 0.95)
                return _stub_ai_message(
                    tool_calls=[{"name": call["name"], "args": args, "id": "tc"}]
                )
        return _stub_ai_message()


def _install_stub_llms() -> None:
    _router_logic._workflow_llm = _StubWorkflowLLM()
    _router_logic._fresh_llm = _StubWorkflowLLM()


class _StubNarrowLLM:
    """Pretends to be the bound-tools LLM inside ``narrow_search``.

    Always returns an ``AIMessage`` with a ``commit_narrow`` tool call so
    the agent commits on the very first turn — useful for chip-flow and
    downstream tests that don't want to script a multi-turn narrowing
    conversation.
    """

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "commit_narrow",
                    "args": {
                        "search_text": "*",
                        "domain": "",
                        "anonymization": "",
                        "study_id": "",
                    },
                    "id": "tc-commit",
                }
            ],
        )


def _install_narrow_stub_commit() -> None:
    """Force ``narrow_search`` to commit immediately (no LLM, no questions)."""
    _narrow_mod._llm = None  # type: ignore[attr-defined]
    _narrow_mod._get_llm = lambda: _StubNarrowLLM()  # type: ignore[assignment]


def _initial_chip_state(thread_id: str) -> dict:
    """Initial state that pins the legacy chip path (skips ``narrow_search``).

    Done by setting ``current_step=choose_domain``; ``_dispatch_fresh`` will
    then route to the chip node before the narrowing subagent runs.
    """
    return {
        "messages": [],
        "thread_id": thread_id,
        "user_id": "u",
        "current_step": RA_STEP_CHOOSE_DOMAIN,
    }


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

_PATCHED = False


def _patch_search() -> None:
    global _PATCHED
    if _PATCHED:
        return

    async def _fake_search(**_: Any) -> list[dict]:
        return [
            {
                "content": "Mock product for tests",
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

    # Patch the LLM-based intent extractor to a deterministic pass-through.
    _extract_mod.extract_search_intent = lambda text: {  # type: ignore[assignment]
        "search_text": (text or "").strip() or "*",
        "study_id": "",
    }

    # Patch MCP facet prefetch to return nothing so the node skips writing
    # to state and downstream chips fall through to the hardcoded defaults.
    async def _no_facets() -> dict:
        return {}

    _prefetch_mod.mcp_search_client.list_facets = _no_facets  # type: ignore[attr-defined]

    _PATCHED = True


def _parent_graph() -> Any:
    """Tiny parent graph with a stub faq agent (no Tavily/LLM)."""

    def recover(state: AppState) -> dict:
        patch: dict = {}
        defaults = {
            "active_flow": "request_access",
            "selected_domains": [],
            "selected_anonymization": None,
            "product_type_filter": "all",
            "product_search_results": [],
            "selected_products": [],
            "cart_snapshot": [],
            "generated_form_schema": [],
            "form_answers": {},
            "last_resume_value": None,
            "current_step": "",
            "awaiting_input": False,
            "pending_prompt": None,
        }
        for k, v in defaults.items():
            if state.get(k) is None:
                patch[k] = v
        return patch

    def fake_faq(state: AppState) -> dict:
        return {"messages": [AIMessage(content="(faq answer)")], "mode": "faq"}

    _patch_search()
    _install_stub_llms()
    _install_narrow_stub_commit()
    ra_sub = build_request_access_subgraph()
    b = StateGraph(AppState)
    b.add_node("recover_state", recover)
    b.add_node("request_access_subgraph", ra_sub)
    b.add_node("faq_kb_agent", fake_faq)
    b.add_edge(START, "recover_state")
    b.add_edge("recover_state", "request_access_subgraph")
    b.add_edge("request_access_subgraph", END)
    b.add_edge("faq_kb_agent", END)
    return b.compile(checkpointer=InMemorySaver())


def _subgraph_values(graph: Any, cfg: dict) -> dict:
    s = graph.get_state(cfg, subgraphs=True)
    for task in s.tasks:
        if task.state:
            return dict(task.state.values or {})
    return dict(s.values or {})


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
# Tests                                                                       #
# --------------------------------------------------------------------------- #


def test_default_first_turn_interrupts_on_narrow_message() -> None:
    """The new default flow runs the conversational narrowing subagent first.

    The chip-based ``choose_domain`` step is no longer the entry point —
    the narrowing subagent is. This test verifies that with no
    ``current_step`` pin, a fresh thread pauses on a ``narrow_message``
    interrupt instead. We let the LLM behave naturally here by using a
    scripted variant that asks one question.
    """

    class _AskOnceLLM:
        async def ainvoke(self, messages: list[Any]) -> AIMessage:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "ask_user",
                        "args": {"message": "Which domain are you interested in?"},
                        "id": "tc-ask-1",
                    }
                ],
            )

    _narrow_mod._llm = None  # type: ignore[attr-defined]
    _narrow_mod._get_llm = lambda: _AskOnceLLM()  # type: ignore[assignment]
    g = _parent_graph()  # NOTE: ``_parent_graph`` re-installs the commit stub.
    # Re-override after _parent_graph re-installed the commit stub.
    _narrow_mod._get_llm = lambda: _AskOnceLLM()  # type: ignore[assignment]
    cfg = {"configurable": {"thread_id": "t-narrow-1"}}
    _ainvoke(g, {"messages": [], "thread_id": "t-narrow-1", "user_id": "u"}, cfg)

    val = _pending_interrupt(g, cfg)
    assert val is not None, "expected the narrowing subagent to interrupt"
    assert val["type"] == "narrow_message"
    assert val["step"] == RA_STEP_NARROW_SEARCH
    assert "domain" in (val.get("message") or "").lower()


def test_chip_first_turn_interrupts_on_choose_domain() -> None:
    g = _parent_graph()
    cfg = {"configurable": {"thread_id": "t1"}}
    _ainvoke(g, _initial_chip_state("t1"), cfg)

    val = _pending_interrupt(g, cfg)
    assert val is not None
    assert val["type"] == "facet_selection"
    assert val["facet"] == "domain"
    assert val["step"] == RA_STEP_CHOOSE_DOMAIN


def test_chip_resume_with_facet_answer_advances_to_anonymization() -> None:
    g = _parent_graph()
    cfg = {"configurable": {"thread_id": "t2"}}
    _ainvoke(g, _initial_chip_state("t2"), cfg)
    _ainvoke(g, Command(resume={"facet": "domain", "value": "commercial"}), cfg)

    sv = _subgraph_values(g, cfg)
    assert sv.get("selected_domains") == ["commercial"]

    val = _pending_interrupt(g, cfg)
    assert val is not None
    assert val["facet"] == "anonymization"


def test_chip_resume_past_anonymization_runs_search_and_pauses_on_products() -> None:
    g = _parent_graph()
    cfg = {"configurable": {"thread_id": "t3"}}
    _ainvoke(g, _initial_chip_state("t3"), cfg)
    _ainvoke(g, Command(resume={"facet": "domain", "value": "commercial"}), cfg)
    _ainvoke(g, Command(resume={"facet": "anonymization", "value": "deidentified"}), cfg)

    sv = _subgraph_values(g, cfg)
    assert sv.get("selected_anonymization") == "deidentified"
    assert sv.get("product_search_results"), "search_products should have populated results"

    val = _pending_interrupt(g, cfg)
    assert val is not None
    assert val["type"] == "product_selection"


def test_navigation_routes_refine_intent_through_narrow_search() -> None:
    """Textual refine intents ("change domain", "change anonymization") now
    route through the conversational narrowing subagent.

    Contract:
      * Downstream artifacts (search results, cart) are cleared so the
        flow restarts at narrowing.
      * Already-selected facets are PRESERVED — the agent needs them as
        context for single-facet refinements. ``commit_narrow`` will
        overwrite authoritatively.
      * The user's raw text is stashed as ``narrow_refine_hint`` so the
        agent can act on the intent without re-asking.
    """

    # Script narrow_search to ask one question so we can verify we landed
    # there (rather than the chip picker).
    class _AskOnceLLM:
        async def ainvoke(self, messages: list[Any]) -> AIMessage:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "ask_user",
                        "args": {"message": "Which domain do you want?"},
                        "id": "tc-ask",
                    }
                ],
            )

    g = _parent_graph()
    cfg = {"configurable": {"thread_id": "t4"}}
    _ainvoke(g, _initial_chip_state("t4"), cfg)
    _ainvoke(g, Command(resume={"facet": "domain", "value": "commercial"}), cfg)
    _ainvoke(g, Command(resume={"facet": "anonymization", "value": "deidentified"}), cfg)

    before = _subgraph_values(g, cfg)
    assert before.get("selected_anonymization") == "deidentified"
    assert before.get("product_search_results")

    # Swap narrow_search's stub to ask-once for this phase of the test.
    _narrow_mod._get_llm = lambda: _AskOnceLLM()  # type: ignore[assignment]

    _ainvoke(g, 
        Command(resume={"action": "user_message", "text": "change domain"}),
        cfg,
    )

    after = _subgraph_values(g, cfg)
    # Facets preserved for the narrowing agent's context.
    assert after.get("selected_domains") == ["commercial"]
    assert after.get("selected_anonymization") == "deidentified"
    # Downstream artifacts cleared.
    assert after.get("product_search_results") == []
    # User's raw text threaded into the hint for the seed message.
    assert after.get("narrow_refine_hint") == "change domain"

    # We're paused on a narrow_message (conversational), NOT a chip picker.
    val = _pending_interrupt(g, cfg)
    assert val is not None
    assert val["type"] == "narrow_message"


def test_user_text_side_message_keeps_workflow_paused() -> None:
    g = _parent_graph()
    cfg = {"configurable": {"thread_id": "t6"}}
    _ainvoke(g, _initial_chip_state("t6"), cfg)

    # Send plain chat text while paused on choose_domain.
    _ainvoke(g, 
        Command(resume={"action": "user_message", "text": "hello there"}),
        cfg,
    )

    # The interrupt must be redisplayed (same facet_selection on domain).
    val = _pending_interrupt(g, cfg)
    assert val is not None
    assert val["type"] == "facet_selection"
    assert val["facet"] == "domain"

    # Side-note AIMessage was appended.
    sv = _subgraph_values(g, cfg)
    msgs = sv.get("messages", [])
    assert any(
        "waiting for your selection" in getattr(m, "content", "").lower() for m in msgs
    )


def test_faq_handoff_preserves_workflow_state() -> None:
    g = _parent_graph()
    cfg = {"configurable": {"thread_id": "t5"}}
    _ainvoke(g, _initial_chip_state("t5"), cfg)
    _ainvoke(g, Command(resume={"facet": "domain", "value": "commercial"}), cfg)

    result = _ainvoke(
        g,
                Command(resume={"action": "user_message", "text": "What is the IHD process?"}),
        cfg,
    )

    # The faq stub's message must surface in the parent result
    msgs = result.get("messages", [])
    assert any(getattr(m, "content", "") == "(faq answer)" for m in msgs)

    # Command.PARENT lifted workflow state up to the parent
    parent = g.get_state(cfg).values
    assert parent.get("active_flow") == "request_access"
    assert parent.get("selected_domains") == ["commercial"]
    assert parent.get("mode") == "faq"
    assert "summary" in (parent.get("faq_context") or {})
