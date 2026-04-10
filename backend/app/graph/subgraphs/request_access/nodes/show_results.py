from __future__ import annotations

import logging

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from app.graph.state import AccessRequestState
from app.service.search_service import SearchService

logger = logging.getLogger(__name__)

_search_service: SearchService | None = None


def _get_search_service() -> SearchService:
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service


def show_results_node(state: AccessRequestState) -> dict:
    query = state.get("search_query", "")
    domain = state.get("selected_domain", "all")
    product_type = state.get("selected_type", "all")
    cached = state.get("search_results", [])

    if cached:
        results = cached
    else:
        logger.info("Searching: query='%s' domain=%s type=%s", query, domain, product_type)
        results = _get_search_service().search_with_filters(
            query=query, domain=domain, product_type=product_type, k=8,
        )

    result_summary = "\n".join(
        f"{i+1}. **{r['metadata'].get('id', '')}** "
        f"[{r['metadata'].get('product_type', 'default')}] — "
        f"{r['content'][:80]}... "
        f"(domain: {r['metadata'].get('domain', '')}, "
        f"sensitivity: {r['metadata'].get('sensitivity', '')})"
        for i, r in enumerate(results)
    )

    response = interrupt({
        "type": "product_selection",
        "message": (
            f"I found {len(results)} data products matching your criteria:\n\n"
            f"{result_summary}\n\n"
            "Select a product to continue, or open the search panel for advanced filtering."
        ),
        "products": results,
        "allow_search": True,
        "allow_multi_select": True,
    })

    action = response.get("action", "select") if isinstance(response, dict) else "select"

    if action == "open_search":
        return {
            "search_results": results,
            "current_step": "search_app",
            "messages": [AIMessage(content="Opening the advanced search panel...")],
        }

    if action == "refine_filters":
        return {
            "search_results": [],
            "current_step": "narrow",
            "selected_domain": "",
            "selected_type": "",
            "messages": [AIMessage(content="Let's refine your search. What domain are you interested in?")],
        }

    products = response.get("products", []) if isinstance(response, dict) else []
    if not products:
        product = response.get("product", response) if isinstance(response, dict) else response
        products = [product] if product else []

    return {
        "search_results": results,
        "selected_products": products,
        "current_step": "fill_form",
        "messages": [
            AIMessage(
                content=f"You selected {len(products)} product(s). Let's fill out the access request forms."
            )
        ],
    }
