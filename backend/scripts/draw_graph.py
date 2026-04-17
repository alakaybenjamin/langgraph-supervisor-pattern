"""Render the compiled parent graph (with subgraphs expanded) to PNG + Mermaid.

This intentionally compiles the graph WITHOUT a checkpointer/store so it can
run offline without Postgres — the visualization output is identical.

Usage:
    cd backend && uv run python scripts/draw_graph.py
"""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from app.graph.faq_agents import faq_kb_agent, general_faq_tavily_agent
from app.graph.nodes.status_check import status_check_node
from app.graph.parent_supervisor import recover_state_node, supervisor_router
from app.graph.state import AppState
from app.graph.subgraphs.request_access import build_request_access_subgraph


def _build_visualization_graph():
    """Compile the same parent graph as ``app.graph.builder.build_graph`` but
    without a checkpointer/store, so we don't need a live database connection
    just to render the diagram.
    """
    ra_subgraph = build_request_access_subgraph()

    b = StateGraph(AppState)
    b.add_node("recover_state", recover_state_node)
    b.add_node("supervisor_router", supervisor_router)
    b.add_node("request_access_subgraph", ra_subgraph)
    b.add_node("faq_kb_agent", faq_kb_agent)
    b.add_node("general_faq_tavily_agent", general_faq_tavily_agent)
    b.add_node("status_agent", status_check_node)

    b.add_edge(START, "recover_state")
    b.add_edge("recover_state", "supervisor_router")
    b.add_edge("request_access_subgraph", END)
    b.add_edge("faq_kb_agent", END)
    b.add_edge("general_faq_tavily_agent", END)
    b.add_edge("status_agent", END)

    return b.compile()


def main() -> None:
    graph = _build_visualization_graph()

    out = Path("docs/graph")
    out.mkdir(parents=True, exist_ok=True)

    top = graph.get_graph()
    detailed = graph.get_graph(xray=1)

    ra_subgraph = build_request_access_subgraph()
    ra_view = ra_subgraph.get_graph()

    (out / "graph.mmd").write_text(top.draw_mermaid())
    (out / "graph_detailed.mmd").write_text(detailed.draw_mermaid())
    (out / "request_access_subgraph.mmd").write_text(ra_view.draw_mermaid())

    (out / "graph.png").write_bytes(top.draw_mermaid_png())
    (out / "graph_detailed.png").write_bytes(detailed.draw_mermaid_png())
    (out / "request_access_subgraph.png").write_bytes(ra_view.draw_mermaid_png())

    print("Wrote:")
    for f in (
        "graph.mmd",
        "graph.png",
        "graph_detailed.mmd",
        "graph_detailed.png",
        "request_access_subgraph.mmd",
        "request_access_subgraph.png",
    ):
        print(f"  - {out / f}")


if __name__ == "__main__":
    main()
