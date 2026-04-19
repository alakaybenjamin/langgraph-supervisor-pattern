"""@file conftest.py
@brief Shared pytest fixtures for the backend test suite.

Currently scoped to one job: pin the A2UI rollout flag to OFF for the
duration of the test session. The legacy interrupt contract
(``type: "facet_selection"`` etc.) is what these tests assert against;
the A2UI v0.9 path has its own dedicated coverage. Without this pin a
developer who flips ``A2UI_ENABLED_INTERRUPTS`` in their local ``.env``
would see spurious failures in ``tests/test_subgraph_flow.py``.
"""

from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _disable_a2ui_for_tests() -> None:
    """Force the legacy interrupt contract for every test.

    ``settings.a2ui_enabled_interrupts`` is a property that re-reads
    ``A2UI_ENABLED_INTERRUPTS`` on each call, so mutating the underlying
    string here is enough to flip the branch in
    ``app.graph.subgraphs.request_access.helpers.build_emit_ui_payload``.
    """
    original = settings.A2UI_ENABLED_INTERRUPTS
    settings.A2UI_ENABLED_INTERRUPTS = ""
    try:
        yield
    finally:
        settings.A2UI_ENABLED_INTERRUPTS = original
