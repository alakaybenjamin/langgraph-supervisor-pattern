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


def search_node(state: AccessRequestState) -> dict:
    query = state.get("search_query", "")
    cached = state.get("search_results", [])

    if cached:
        results = cached
    else:
        logger.info("Searching data products: '%s'", query)
        results = _get_search_service().search(query, k=5)

    result_summary = "\n".join(
        f"{i+1}. **{r['metadata'].get('id', '')}** [{r['metadata'].get('product_type', 'default')}] — {r['content'][:80]}... (domain: {r['metadata'].get('domain', '')}, sensitivity: {r['metadata'].get('sensitivity', '')})"
        for i, r in enumerate(results)
    )

    selected = interrupt({
        "type": "product_selection",
        "message": f"I found these data products matching your request:\n\n{result_summary}\n\nPlease select a product to continue.",
        "products": results,
    })

    selected_product = selected.get("product", selected) if isinstance(selected, dict) else selected

    return {
        "search_results": results,
        "selected_product": selected_product,
        "current_step": "fill_form",
        "messages": [AIMessage(content=f"You selected: {selected_product.get('metadata', {}).get('id', 'unknown')} — proceeding to the access request form.")],
    }
