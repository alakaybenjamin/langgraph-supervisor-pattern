from __future__ import annotations

"""End-to-end exercise of the request-access subgraph using an in-memory
checkpointer. Exercises: entry interrupt, resume with facet answer, navigation
invalidation, and FAQ handoff to the parent via Command.PARENT.

No database, LLM, or ChromaDB dependencies: ``search_products`` is patched to
return a small fixed product list so we don't hit OpenAI embeddings.
"""

from typing import Any

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

import app.graph.router_logic as _router_logic
import app.graph.subgraphs.request_access.nodes.steps as _steps_mod
from app.graph.subgraphs.request_access import build_request_access_subgraph
from app.graph.state import AppState, RA_STEP_CHOOSE_DOMAIN


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
                return _stub_ai_message(
                    tool_calls=[{"name": call["name"], "args": call["args"], "id": "tc"}]
                )
        return _stub_ai_message()


def _install_stub_llms() -> None:
    _router_logic._workflow_llm = _StubWorkflowLLM()
    _router_logic._fresh_llm = _StubWorkflowLLM()


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

_PATCHED = False


def _patch_search() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _steps_mod.build_search_products_query = lambda **_: [  # type: ignore[assignment]
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


def test_first_turn_interrupts_on_choose_domain() -> None:
    g = _parent_graph()
    cfg = {"configurable": {"thread_id": "t1"}}
    g.invoke({"messages": [], "thread_id": "t1", "user_id": "u"}, cfg)

    val = _pending_interrupt(g, cfg)
    assert val is not None
    assert val["type"] == "facet_selection"
    assert val["facet"] == "domain"
    assert val["step"] == RA_STEP_CHOOSE_DOMAIN


def test_resume_with_facet_answer_advances_to_anonymization() -> None:
    g = _parent_graph()
    cfg = {"configurable": {"thread_id": "t2"}}
    g.invoke({"messages": [], "thread_id": "t2", "user_id": "u"}, cfg)
    g.invoke(Command(resume={"facet": "domain", "value": "commercial"}), cfg)

    sv = _subgraph_values(g, cfg)
    assert sv.get("selected_domains") == ["commercial"]

    val = _pending_interrupt(g, cfg)
    assert val is not None
    assert val["facet"] == "anonymization"


def test_resume_past_anonymization_runs_search_and_pauses_on_products() -> None:
    g = _parent_graph()
    cfg = {"configurable": {"thread_id": "t3"}}
    g.invoke({"messages": [], "thread_id": "t3", "user_id": "u"}, cfg)
    g.invoke(Command(resume={"facet": "domain", "value": "commercial"}), cfg)
    g.invoke(Command(resume={"facet": "anonymization", "value": "deidentified"}), cfg)

    sv = _subgraph_values(g, cfg)
    assert sv.get("selected_anonymization") == "deidentified"
    assert sv.get("product_search_results"), "search_products should have populated results"

    val = _pending_interrupt(g, cfg)
    assert val is not None
    assert val["type"] == "product_selection"


def test_navigation_clears_downstream_state() -> None:
    g = _parent_graph()
    cfg = {"configurable": {"thread_id": "t4"}}
    g.invoke({"messages": [], "thread_id": "t4", "user_id": "u"}, cfg)
    g.invoke(Command(resume={"facet": "domain", "value": "commercial"}), cfg)
    g.invoke(Command(resume={"facet": "anonymization", "value": "deidentified"}), cfg)

    before = _subgraph_values(g, cfg)
    assert before.get("selected_anonymization") == "deidentified"
    assert before.get("product_search_results")

    g.invoke(
        Command(resume={"action": "user_message", "text": "change domain"}),
        cfg,
    )

    after = _subgraph_values(g, cfg)
    assert after.get("selected_domains") == []
    assert after.get("selected_anonymization") is None
    assert after.get("product_search_results") == []

    val = _pending_interrupt(g, cfg)
    assert val is not None
    assert val["facet"] == "domain"


def test_user_text_side_message_keeps_workflow_paused() -> None:
    g = _parent_graph()
    cfg = {"configurable": {"thread_id": "t6"}}
    g.invoke({"messages": [], "thread_id": "t6", "user_id": "u"}, cfg)

    # Send plain chat text while paused on choose_domain.
    g.invoke(
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
    g.invoke({"messages": [], "thread_id": "t5", "user_id": "u"}, cfg)
    g.invoke(Command(resume={"facet": "domain", "value": "commercial"}), cfg)

    result = g.invoke(
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
