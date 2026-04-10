from __future__ import annotations

import operator
from typing import Annotated

from typing_extensions import TypedDict


class SupervisorState(TypedDict):
    messages: Annotated[list, operator.add]
    active_intent: str
    thread_id: str
    user_id: str


class AccessRequestState(TypedDict):
    messages: Annotated[list, operator.add]
    current_step: str
    # Facet narrowing
    selected_domain: str
    selected_type: str
    # Search
    search_query: str
    search_results: list
    # Cart (multi-product)
    selected_products: list
    current_product_index: int
    # Forms (keyed by product id)
    form_drafts: dict
    form_template: dict | None
