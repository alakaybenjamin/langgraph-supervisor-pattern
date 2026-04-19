from __future__ import annotations

import operator
from typing import Annotated, Any, Literal

from typing_extensions import NotRequired, TypedDict


class AppState(TypedDict):
    """Shared superset state for the parent supervisor graph and the
    request-access subgraph. The subgraph is compiled against this schema so
    that state propagates seamlessly between parent and child nodes.
    """

    # Core conversation
    messages: Annotated[list, operator.add]
    thread_id: str
    user_id: str

    # Parent-level orchestration
    active_flow: NotRequired[Literal["request_access", "none"]]
    mode: NotRequired[Literal["workflow", "faq", "idle"]]
    active_intent: NotRequired[str]
    supervisor_decision: NotRequired[str]
    faq_context: NotRequired[dict]
    paused_workflow_summary: NotRequired[str]

    # Request-access workflow
    current_step: NotRequired[str]
    awaiting_input: NotRequired[bool]
    pending_prompt: NotRequired[dict | None]
    selected_domains: NotRequired[list[str]]
    selected_anonymization: NotRequired[str | None]
    product_type_filter: NotRequired[str]
    product_search_results: NotRequired[list[dict]]
    selected_products: NotRequired[list[dict]]
    cart_snapshot: NotRequired[list[dict]]
    generated_form_schema: NotRequired[list[dict]]
    form_answers: NotRequired[dict]
    last_workflow_node: NotRequired[str]
    nav_intent: NotRequired[str | None]
    invalidated_from_step: NotRequired[str | None]
    last_resume_value: NotRequired[Any]
    ra_search_query: NotRequired[str]
    ra_study_id: NotRequired[str]
    submit_confirmed: NotRequired[bool]
    last_request_id: NotRequired[str]

    # Canonical facet chips fetched from the MCP search server
    # (``{"domains": [...], "anonymization": [...]}``). Populated once per
    # subgraph entry by the ``mcp_prefetch_facets`` node and read by
    # ``choose_domain`` / ``choose_anonymization`` when rendering chips.
    mcp_facet_cache: NotRequired[dict]

    # Conversational narrowing subagent state. The ``narrow_search`` node owns
    # this dict end-to-end: it carries the agent's internal message log
    # (system prompt, tool calls, tool results), a turn counter for the
    # defensive cap, and the id of the most recent ``ask_user`` tool call so
    # the next iteration can pair the user's reply with the right tool call.
    # Cleared (set to ``None``) once the agent commits via ``commit_narrow``.
    narrow_state: NotRequired[dict | None]

    # Free-text hint handed to the next ``narrow_search`` execution when the
    # user navigates back to re-narrow via plain chat (e.g. "change the
    # anonymization to identified"). Consumed once by
    # ``_seed_initial_user_message`` and cleared on commit.
    narrow_refine_hint: NotRequired[str | None]

    # Supervisor clarification follow-up: set when the supervisor emitted a
    # "Did you mean…?" reply. On the next turn, if the user affirms (yes /
    # correct / …), the supervisor dispatches to the saved candidate intent
    # without re-running the classifier. If the user negates or rephrases,
    # this field is cleared.
    pending_clarification: NotRequired[dict | None]


# ---------------------------------------------------------------------------
# Workflow step identifiers
# ---------------------------------------------------------------------------

RA_STEP_NARROW_SEARCH = "narrow_search"
RA_STEP_CHOOSE_DOMAIN = "choose_domain"
RA_STEP_CHOOSE_ANONYMIZATION = "choose_anonymization"
RA_STEP_SEARCH_PRODUCTS = "search_products"
RA_STEP_CHOOSE_PRODUCTS = "choose_products"
RA_STEP_SHOW_CART = "show_cart"
RA_STEP_GENERATE_FORM = "generate_dynamic_form"
RA_STEP_FILL_FORM = "fill_form"
RA_STEP_SUBMIT = "submit_request"

# ``RA_STEPS_ORDER`` is the canonical linear ordering used by
# ``compute_downstream_invalidation`` to decide which workflow artifacts to
# clear when the user navigates back. The default *entry* path skips the
# chip nodes (``narrow_search`` collects domain + anonymization
# conversationally instead), but ``choose_domain`` / ``choose_anonymization``
# remain in the order so that an explicit nav to either one still triggers
# the same "clear domain → also clear anonymization → also clear search
# results → …" cascade as before.
RA_STEPS_ORDER: list[str] = [
    RA_STEP_NARROW_SEARCH,
    RA_STEP_CHOOSE_DOMAIN,
    RA_STEP_CHOOSE_ANONYMIZATION,
    RA_STEP_SEARCH_PRODUCTS,
    RA_STEP_CHOOSE_PRODUCTS,
    RA_STEP_SHOW_CART,
    RA_STEP_GENERATE_FORM,
    RA_STEP_FILL_FORM,
    RA_STEP_SUBMIT,
]

RA_STEP_TO_NODE: dict[str, str] = {
    RA_STEP_NARROW_SEARCH: "narrow_search",
    RA_STEP_CHOOSE_DOMAIN: "choose_domain",
    RA_STEP_CHOOSE_ANONYMIZATION: "choose_anonymization",
    RA_STEP_SEARCH_PRODUCTS: "search_products",
    RA_STEP_CHOOSE_PRODUCTS: "choose_products",
    RA_STEP_SHOW_CART: "show_cart",
    RA_STEP_GENERATE_FORM: "generate_dynamic_form",
    RA_STEP_FILL_FORM: "fill_form",
    RA_STEP_SUBMIT: "submit_request",
}


# ---------------------------------------------------------------------------
# Interrupt payload schemas (documentation-only TypedDicts)
# ---------------------------------------------------------------------------


class FacetInterrupt(TypedDict):
    type: Literal["facet_selection"]
    message: str
    facet: str
    options: list[dict]
    step: str
    prompt_id: str


class ProductSelectionInterrupt(TypedDict):
    type: Literal["product_selection"]
    message: str
    products: list[dict]
    allow_search: bool
    allow_multi_select: bool
    step: str
    prompt_id: str


class CartReviewInterrupt(TypedDict):
    type: Literal["cart_review"]
    message: str
    products: list[dict]
    actions: list[dict]
    step: str
    prompt_id: str


class McpAppInterrupt(TypedDict):
    type: Literal["mcp_app"]
    resource_uri: str
    mcp_endpoint: str
    tool_name: str
    tool_args: dict
    context: dict
    step: str
    prompt_id: str


class ConfirmationInterrupt(TypedDict):
    type: Literal["confirmation"]
    message: str
    products: list[dict]
    form_data: dict
    products_summary: str
    actions: list[dict]
    step: str
    prompt_id: str


class NarrowMessageInterrupt(TypedDict):
    """Plain-text conversational prompt emitted by the narrowing subagent.

    Carries no chips, options, or actions — the frontend renders the
    ``message`` as an ordinary assistant chat bubble. The user replies via
    the normal chat input; ``chat_service`` wraps that text as a
    ``Command(resume={"action": "user_message", "text": ...})`` which
    feeds straight back into the agent loop.
    """

    type: Literal["narrow_message"]
    message: str
    step: str
    prompt_id: str


InterruptPayload = (
    FacetInterrupt
    | ProductSelectionInterrupt
    | CartReviewInterrupt
    | McpAppInterrupt
    | ConfirmationInterrupt
    | NarrowMessageInterrupt
)


# Kept for any historical imports.
SupervisorState = AppState
