"""@file test_a2ui_builders.py
@brief Unit coverage for the A2UI v0.9 builders and the
``build_emit_ui_payload`` rollout branch.

These tests intentionally re-enable the A2UI flag (the session-wide
``conftest.py`` pin defaults it off) so we can assert the new payload
shape without affecting the legacy contract tests.
"""

from __future__ import annotations

import pytest

from app.a2ui import (
    A2UI_CATALOG_ID,
    A2UI_SURFACE_PREFIX,
    A2UI_VERSION,
    build_facet_selection_surface,
    build_product_selection_surface,
)
from app.core.config import settings
from app.graph.subgraphs.request_access.helpers import build_emit_ui_payload


@pytest.fixture
def _enable_a2ui_facet():
    """Locally re-enable the ``facet_selection`` A2UI branch."""
    original = settings.A2UI_ENABLED_INTERRUPTS
    settings.A2UI_ENABLED_INTERRUPTS = "facet_selection"
    try:
        yield
    finally:
        settings.A2UI_ENABLED_INTERRUPTS = original


@pytest.fixture
def _enable_a2ui_products():
    """Locally re-enable the ``product_selection`` A2UI branch."""
    original = settings.A2UI_ENABLED_INTERRUPTS
    settings.A2UI_ENABLED_INTERRUPTS = "product_selection"
    try:
        yield
    finally:
        settings.A2UI_ENABLED_INTERRUPTS = original


def test_build_facet_selection_surface_shapes_v09_payload() -> None:
    payload = build_facet_selection_surface(
        step="choose_domain",
        prompt="Pick a domain.",
        facet="domain",
        options=[{"id": "commercial", "label": "Commercial"}],
        prompt_id="abc",
    )

    assert payload["type"] == "a2ui"
    assert payload["step"] == "choose_domain"
    assert payload["prompt_id"] == "abc"
    assert payload["catalog_id"] == A2UI_CATALOG_ID
    assert payload["surface_id"].startswith(A2UI_SURFACE_PREFIX)
    # The chat bubble owns the prompt text; ``message`` MUST be the
    # exact prompt the host renders, otherwise the user sees the
    # placeholder fallback in chat.service.ts.
    assert payload["message"] == "Pick a domain."
    assert payload["resume_hint"] == {
        "ui_type": "facet_selection",
        "facet": "domain",
    }

    msgs = payload["a2ui_messages"]
    assert len(msgs) == 3
    # All three messages must carry the v0.9 version tag and target the
    # same surface, otherwise the renderer will silently drop them.
    surface_id = payload["surface_id"]
    for m in msgs:
        assert m["version"] == A2UI_VERSION
        body = next(v for k, v in m.items() if k != "version")
        assert body["surfaceId"] == surface_id

    # The data model is chips-only: prompt is intentionally omitted so
    # the FacetChipRow component cannot accidentally double-render it
    # alongside the chat bubble.
    data_model = msgs[1]["updateDataModel"]["value"]
    assert "prompt" not in data_model
    assert data_model["facet"] == "domain"
    assert data_model["options"] == [{"id": "commercial", "label": "Commercial"}]

    update_components = msgs[2]["updateComponents"]
    root = update_components["components"][0]
    assert root["component"] == "FacetChipRow"
    assert "prompt" not in root
    assert root["options"] == {"path": "/options"}
    event_ctx = root["onSelect"]["event"]["context"]
    assert event_ctx["facet"] == "domain"
    assert event_ctx["step"] == "choose_domain"
    assert event_ctx["prompt_id"] == "abc"


def test_build_emit_ui_payload_routes_to_a2ui_when_flag_enabled(
    _enable_a2ui_facet: None,
) -> None:
    payload = build_emit_ui_payload(
        ui_type="facet_selection",
        message="Pick anonymization.",
        facet="anonymization",
        options=[{"id": "deidentified", "label": "De-identified"}],
        step="choose_anonymization",
        prompt_id="pid-1",
    )

    assert payload["type"] == "a2ui"
    assert payload["resume_hint"]["facet"] == "anonymization"
    assert payload["prompt_id"] == "pid-1"


def test_build_emit_ui_payload_keeps_legacy_when_flag_disabled() -> None:
    # No fixture: the conftest autouse pin keeps A2UI off here.
    payload = build_emit_ui_payload(
        ui_type="facet_selection",
        message="Pick anonymization.",
        facet="anonymization",
        options=[{"id": "deidentified", "label": "De-identified"}],
        step="choose_anonymization",
        prompt_id="pid-2",
    )

    assert payload["type"] == "facet_selection"
    assert payload["facet"] == "anonymization"
    assert "a2ui_messages" not in payload


def test_build_emit_ui_payload_falls_through_for_unported_ui_types(
    _enable_a2ui_facet: None,
) -> None:
    """Phases 5-6 aren't wired yet; these still need to use the legacy path."""
    payload = build_emit_ui_payload(
        ui_type="confirmation",
        message="Confirm submission?",
        step="confirm",
        prompt_id="pid-3",
    )

    assert payload["type"] == "confirmation"
    assert "a2ui_messages" not in payload


# ---------------------------------------------------------------------------
# ProductPicker (Phase 4)
# ---------------------------------------------------------------------------


def _sample_product(pid: str = "dp-1") -> dict:
    return {
        "content": "Sample product for tests",
        "metadata": {
            "id": pid,
            "product_type": "default",
            "domain": "commercial",
            "sensitivity": "low",
        },
        "score": 1.0,
    }


def test_build_product_selection_surface_shapes_v09_payload() -> None:
    payload = build_product_selection_surface(
        step="choose_products",
        prompt="Pick the products you need.",
        products=[_sample_product("dp-1"), _sample_product("dp-2")],
        prompt_id="pid-prod",
    )

    assert payload["type"] == "a2ui"
    assert payload["message"] == "Pick the products you need."
    assert payload["step"] == "choose_products"
    assert payload["prompt_id"] == "pid-prod"
    assert payload["catalog_id"] == A2UI_CATALOG_ID
    assert payload["surface_id"].startswith(A2UI_SURFACE_PREFIX)
    assert payload["resume_hint"] == {"ui_type": "product_selection"}

    msgs = payload["a2ui_messages"]
    assert len(msgs) == 3
    surface_id = payload["surface_id"]
    for m in msgs:
        assert m["version"] == A2UI_VERSION
        body = next(v for k, v in m.items() if k != "version")
        assert body["surfaceId"] == surface_id

    # Products live in the data model so the renderer can re-bind them
    # if a future agent message swaps them out (e.g. a search-refine
    # round-trip).
    data_model = msgs[1]["updateDataModel"]["value"]
    assert [p["metadata"]["id"] for p in data_model["products"]] == ["dp-1", "dp-2"]

    root = msgs[2]["updateComponents"]["components"][0]
    assert root["component"] == "ProductPicker"
    assert root["products"] == {"path": "/products"}
    # The four user-facing actions must exist with stable event names
    # (the ChatService adapter routes by event ``name``, not by the
    # property name).
    assert root["onConfirm"]["event"]["name"] == "product.confirm"
    assert root["onOpenSearch"]["event"]["name"] == "product.open_search"
    assert root["onRefine"]["event"]["name"] == "product.refine"
    assert root["onToggle"]["event"]["name"] == "product.toggle"
    # All actions carry the same routing context so any of them can
    # resume the workflow without extra threading.
    for prop in ("onConfirm", "onOpenSearch", "onRefine", "onToggle"):
        ctx = root[prop]["event"]["context"]
        assert ctx["step"] == "choose_products"
        assert ctx["prompt_id"] == "pid-prod"


def test_build_emit_ui_payload_routes_products_to_a2ui_when_flag_enabled(
    _enable_a2ui_products: None,
) -> None:
    payload = build_emit_ui_payload(
        ui_type="product_selection",
        message="Pick the products you need.",
        products=[_sample_product()],
        step="choose_products",
        prompt_id="pid-prod",
    )

    assert payload["type"] == "a2ui"
    assert payload["resume_hint"] == {"ui_type": "product_selection"}
    # ``build_emit_ui_payload`` runs products through normalize_products
    # before handing them to the builder, so the surface always sees the
    # canonical metadata shape regardless of what the caller passed.
    products = payload["a2ui_messages"][1]["updateDataModel"]["value"]["products"]
    assert products[0]["metadata"]["id"] == "dp-1"
