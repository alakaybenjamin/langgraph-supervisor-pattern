from __future__ import annotations

import logging
import uuid
from typing import Any

from app.service.search_service import SearchService

logger = logging.getLogger(__name__)

_search_service: SearchService | None = None

DOMAIN_OPTIONS: list[dict[str, str]] = [
    {"id": "commercial", "label": "Commercial"},
    {"id": "clinical", "label": "Clinical"},
    {"id": "corporate", "label": "Corporate"},
    {"id": "finance", "label": "Finance"},
    {"id": "medical_affairs", "label": "Medical Affairs"},
    {"id": "operations", "label": "Operations"},
    {"id": "r_and_d", "label": "R&D"},
    {"id": "all", "label": "All Domains"},
]

PRODUCT_TYPE_OPTIONS: list[dict[str, str]] = [
    {"id": "onyx", "label": "Onyx"},
    {"id": "ddf", "label": "DDF"},
    {"id": "default", "label": "Default"},
    {"id": "all", "label": "Any Type"},
]

ANONYMIZATION_OPTIONS: list[dict[str, str]] = [
    {"id": "identified", "label": "Identified data (standard access)"},
    {"id": "limited", "label": "Limited / aggregated"},
    {"id": "deidentified", "label": "De-identified only"},
]

CART_ACTIONS: list[dict[str, str]] = [
    {"id": "fill_forms", "label": "Fill Access Forms"},
    {"id": "add_more", "label": "+ Add More Products"},
    {"id": "change_selection", "label": "Change Selection"},
]

CART_ACTIONS_READONLY: list[dict[str, str]] = [
    {"id": "back", "label": "Back to workflow"},
]

SEARCH_APP_PAYLOAD: dict[str, Any] = {
    "type": "mcp_app",
    "resource_uri": "ui://search-app/mcp-app.html",
    "mcp_endpoint": "/mcp/search-app",
    "tool_name": "search-data-products",
    "tool_args": {"filters": {}},
    "context": {},
}

QUESTION_FORM_PAYLOAD: dict[str, Any] = {
    "type": "mcp_app",
    "resource_uri": "ui://question-form/mcp-app.html",
    "mcp_endpoint": "/mcp/question-form",
    "tool_name": "open-question-form",
    "tool_args": {},
    "context": {},
}


def get_search_service() -> SearchService:
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service


def as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def normalize_product(product: Any) -> dict[str, Any]:
    if not isinstance(product, dict):
        return {
            "content": as_str(product),
            "metadata": {
                "id": "unknown",
                "product_type": "unknown",
                "domain": "unknown",
                "sensitivity": "unknown",
            },
            "score": 0.0,
        }

    metadata = product.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    pid = (
        metadata.get("id")
        or product.get("id")
        or product.get("product_id")
        or "unknown"
    )
    ptype = (
        metadata.get("product_type")
        or product.get("product_type")
        or product.get("type")
        or "unknown"
    )
    domain = metadata.get("domain") or product.get("domain") or "unknown"
    sensitivity = (
        metadata.get("sensitivity")
        or product.get("sensitivity")
        or "unknown"
    )
    content = (
        product.get("content")
        or product.get("description")
        or product.get("text")
        or ""
    )
    score = product.get("score", 0.0)
    try:
        score_value = float(score)
    except (TypeError, ValueError):
        score_value = 0.0

    return {
        "content": as_str(content),
        "metadata": {
            "id": as_str(pid, "unknown"),
            "product_type": as_str(ptype, "unknown"),
            "domain": as_str(domain, "unknown"),
            "sensitivity": as_str(sensitivity, "unknown"),
        },
        "score": score_value,
    }


def normalize_products(products: Any) -> list[dict[str, Any]]:
    if not isinstance(products, list):
        return []
    return [normalize_product(p) for p in products]


def canonicalize_ui_payload(
    *,
    ui_type: str,
    facet: str | None,
    options: list[dict] | None,
    actions: list[dict] | None,
    allow_search: bool,
    allow_multi_select: bool,
) -> tuple[list[dict] | None, list[dict] | None, bool, bool]:
    canonical_options = options
    canonical_actions = actions
    canonical_allow_search = allow_search
    canonical_allow_multi_select = allow_multi_select

    if ui_type == "facet_selection":
        if facet == "domain":
            canonical_options = DOMAIN_OPTIONS
        elif facet == "product_type":
            canonical_options = PRODUCT_TYPE_OPTIONS
        elif facet == "anonymization":
            canonical_options = ANONYMIZATION_OPTIONS
    elif ui_type == "cart_review":
        canonical_actions = CART_ACTIONS
    elif ui_type == "product_selection":
        canonical_allow_search = True
        canonical_allow_multi_select = True

    return (
        canonical_options,
        canonical_actions,
        canonical_allow_search,
        canonical_allow_multi_select,
    )


def build_search_products_query(
    *,
    query: str,
    domain: str,
    product_type: str,
    k: int = 8,
) -> list[dict]:
    svc = get_search_service()
    results = svc.search_with_filters(
        query=query, domain=domain, product_type=product_type, k=k,
    )
    logger.info(
        "search_products: query=%r domain=%s type=%s -> %d results",
        query, domain, product_type, len(results),
    )
    return results


def build_emit_ui_payload(
    *,
    ui_type: str,
    message: str,
    options: list[dict] | None = None,
    products: list[dict] | None = None,
    actions: list[dict] | None = None,
    facet: str | None = None,
    allow_search: bool = False,
    allow_multi_select: bool = False,
    step: str = "",
    prompt_id: str | None = None,
) -> dict[str, Any]:
    (
        options,
        actions,
        allow_search,
        allow_multi_select,
    ) = canonicalize_ui_payload(
        ui_type=ui_type,
        facet=facet,
        options=options,
        actions=actions,
        allow_search=allow_search,
        allow_multi_select=allow_multi_select,
    )

    payload: dict[str, Any] = {
        "type": ui_type,
        "message": message,
        "step": step,
        "prompt_id": prompt_id or str(uuid.uuid4()),
    }
    if options is not None:
        payload["options"] = options
    if products is not None:
        payload["products"] = normalize_products(products)
    if actions is not None:
        payload["actions"] = actions
    if facet is not None:
        payload["facet"] = facet
    if allow_search:
        payload["allow_search"] = True
    if allow_multi_select:
        payload["allow_multi_select"] = True
    return payload


def merge_form_schema_for_products(
    products: list[dict],
) -> list[dict]:
    """Minimal placeholder schema per product id for the dynamic form step."""
    schema: list[dict] = []
    for p in products:
        meta = p.get("metadata", {}) if isinstance(p, dict) else {}
        pid = meta.get("id", "unknown")
        schema.append(
            {
                "product_id": pid,
                "title": f"Access request — {pid}",
                "fields": [
                    {"name": "business_justification", "label": "Business justification", "type": "textarea"},
                    {"name": "data_scope", "label": "Intended data use", "type": "text"},
                ],
            }
        )
    return schema
