from __future__ import annotations

from app.graph.subgraphs.request_access.nodes.navigation import (
    compute_downstream_invalidation,
)
from app.graph.state import (
    RA_STEP_CHOOSE_DOMAIN,
    RA_STEP_CHOOSE_PRODUCTS,
    RA_STEP_FILL_FORM,
)


def test_invalidate_from_domain_clears_all_downstream() -> None:
    patch = compute_downstream_invalidation(RA_STEP_CHOOSE_DOMAIN)
    assert patch["selected_domains"] == []
    assert patch["selected_anonymization"] is None
    assert patch["product_search_results"] == []
    assert patch["selected_products"] == []
    assert patch["generated_form_schema"] == []
    assert patch["form_answers"] == {}
    assert patch["submit_confirmed"] is False
    assert patch["pending_prompt"] is None
    assert patch["awaiting_input"] is False


def test_invalidate_from_products_preserves_domain_and_anon() -> None:
    patch = compute_downstream_invalidation(RA_STEP_CHOOSE_PRODUCTS)
    assert "selected_domains" not in patch
    assert "selected_anonymization" not in patch
    assert patch["selected_products"] == []
    assert patch["cart_snapshot"] == []
    assert patch["generated_form_schema"] == []


def test_invalidate_from_fill_form_preserves_selection_and_schema() -> None:
    patch = compute_downstream_invalidation(RA_STEP_FILL_FORM)
    assert "selected_products" not in patch
    assert "generated_form_schema" not in patch
    assert patch["form_answers"] == {}
    assert patch["submit_confirmed"] is False
