"""Parent supervisor graph package.

Layout:

- :mod:`app.graph.state`            — shared ``AppState`` schema + step constants.
- :mod:`app.graph.router_logic`     — deterministic classifiers (FAQ / nav).
- :mod:`app.graph.parent_supervisor` — top-level supervisor router + state recover.
- :mod:`app.graph.faq_agents`       — parent-level FAQ agent nodes.
- :mod:`app.graph.nodes`            — other parent-level nodes (status, …).
- :mod:`app.graph.subgraphs`        — compiled subgraph packages.
- :mod:`app.graph.builder`          — composes the full parent graph.
"""

from app.graph.builder import build_graph, shutdown_graph

__all__ = ["build_graph", "shutdown_graph"]
