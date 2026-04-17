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
    submit_confirmed: NotRequired[bool]
    last_request_id: NotRequired[str]


# ---------------------------------------------------------------------------
# Workflow step identifiers
# ---------------------------------------------------------------------------

RA_STEP_CHOOSE_DOMAIN = "choose_domain"
RA_STEP_CHOOSE_ANONYMIZATION = "choose_anonymization"
RA_STEP_SEARCH_PRODUCTS = "search_products"
RA_STEP_CHOOSE_PRODUCTS = "choose_products"
RA_STEP_SHOW_CART = "show_cart"
RA_STEP_GENERATE_FORM = "generate_dynamic_form"
RA_STEP_FILL_FORM = "fill_form"
RA_STEP_SUBMIT = "submit_request"

RA_STEPS_ORDER: list[str] = [
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


InterruptPayload = (
    FacetInterrupt
    | ProductSelectionInterrupt
    | CartReviewInterrupt
    | McpAppInterrupt
    | ConfirmationInterrupt
)


# Kept for any historical imports.
SupervisorState = AppState
