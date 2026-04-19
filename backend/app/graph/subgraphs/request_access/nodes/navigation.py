from __future__ import annotations

"""Navigation and downstream-invalidation logic for the request-access subgraph.

Three nodes:

- ``handle_navigation`` — reads ``nav_intent`` from state and forwards to
  ``invalidate_downstream_state``.
- ``invalidate_downstream_state`` — clears all workflow artifacts at or after
  the target step.
- ``goto_target_step`` — sets ``current_step`` and hands back to the router.
"""

import logging

from langgraph.types import Command

from app.graph.state import (
    RA_STEP_CHOOSE_ANONYMIZATION,
    RA_STEP_CHOOSE_DOMAIN,
    RA_STEP_CHOOSE_PRODUCTS,
    RA_STEP_FILL_FORM,
    RA_STEP_GENERATE_FORM,
    RA_STEP_NARROW_SEARCH,
    RA_STEP_SEARCH_PRODUCTS,
    RA_STEP_SHOW_CART,
    RA_STEP_SUBMIT,
    RA_STEPS_ORDER,
    AppState,
)

logger = logging.getLogger(__name__)


def compute_downstream_invalidation(step: str) -> dict:
    """Return state updates clearing artifacts at or after ``step`` (inclusive).

    Special case: when ``step == RA_STEP_NARROW_SEARCH`` we preserve
    ``selected_domains`` / ``selected_anonymization`` so the
    conversational narrowing agent can see the user's current filters
    and apply single-facet refinements (e.g. "change anonymization to
    identified") without losing the rest of the context. The agent's
    ``commit_narrow`` overwrites these fields authoritatively.
    """
    try:
        idx = RA_STEPS_ORDER.index(step)
    except ValueError:
        idx = 0

    patch: dict = {"invalidated_from_step": step}
    preserve_facets_for_narrow = step == RA_STEP_NARROW_SEARCH

    # Reset the conversational narrowing transcript whenever we rewind
    # to (or before) the narrowing step.
    if idx <= RA_STEPS_ORDER.index(RA_STEP_NARROW_SEARCH):
        patch["narrow_state"] = None
    if idx <= RA_STEPS_ORDER.index(RA_STEP_CHOOSE_DOMAIN) and not preserve_facets_for_narrow:
        patch["selected_domains"] = []
    if (
        idx <= RA_STEPS_ORDER.index(RA_STEP_CHOOSE_ANONYMIZATION)
        and not preserve_facets_for_narrow
    ):
        patch["selected_anonymization"] = None
    if idx <= RA_STEPS_ORDER.index(RA_STEP_SEARCH_PRODUCTS):
        patch["product_search_results"] = []
        patch["product_type_filter"] = "all"
    if idx <= RA_STEPS_ORDER.index(RA_STEP_CHOOSE_PRODUCTS):
        patch["selected_products"] = []
        patch["cart_snapshot"] = []
    if idx <= RA_STEPS_ORDER.index(RA_STEP_SHOW_CART):
        patch["cart_snapshot"] = []
    if idx <= RA_STEPS_ORDER.index(RA_STEP_GENERATE_FORM):
        patch["generated_form_schema"] = []
    if idx <= RA_STEPS_ORDER.index(RA_STEP_FILL_FORM):
        patch["form_answers"] = {}
    if idx <= RA_STEPS_ORDER.index(RA_STEP_SUBMIT):
        patch["submit_confirmed"] = False
        patch["last_request_id"] = ""

    # Clear any pending prompt so the next step renders fresh
    patch["pending_prompt"] = None
    patch["awaiting_input"] = False
    patch["last_resume_value"] = None
    return patch


def handle_navigation(state: AppState) -> Command:
    """Route to invalidation based on ``nav_intent``; view_cart is read-only."""
    intent = state.get("nav_intent") or ""
    logger.info("handle_navigation: nav_intent=%s", intent)

    if intent == "view_cart":
        return Command(
            update={"last_workflow_node": "handle_navigation"},
            goto="show_cart_readonly",
        )

    return Command(
        update={"last_workflow_node": "handle_navigation"},
        goto="invalidate_downstream_state",
    )


def invalidate_downstream_state(state: AppState) -> Command:
    target = state.get("nav_intent") or RA_STEP_CHOOSE_DOMAIN
    patch = compute_downstream_invalidation(target)
    logger.info("invalidate_downstream_state: cleared from %s", target)
    return Command(
        update={**patch, "last_workflow_node": "invalidate_downstream_state"},
        goto="goto_target_step",
    )


def goto_target_step(state: AppState) -> Command:
    target = state.get("nav_intent") or RA_STEP_CHOOSE_DOMAIN
    logger.info("goto_target_step: current_step=%s", target)
    return Command(
        update={
            "current_step": target,
            "nav_intent": None,
            "last_workflow_node": "goto_target_step",
        },
        goto="route_request_access_turn",
    )
