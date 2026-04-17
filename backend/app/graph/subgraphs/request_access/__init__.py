"""Request-access subgraph package.

Exposes :func:`build_request_access_subgraph` so callers can depend on the
package path rather than the internal module layout.
"""

from app.graph.subgraphs.request_access.graph import build_request_access_subgraph

__all__ = ["build_request_access_subgraph"]
