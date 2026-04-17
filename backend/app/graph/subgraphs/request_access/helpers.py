"""@file helpers.py
@brief Shared helpers for the request-access LangGraph subgraph.

Pure utilities for search, product normalization, and interrupt payloads sent
to the chat UI. No graph nodes live here.

@section request_access_helpers_constants Module constants
- DOMAIN_OPTIONS, PRODUCT_TYPE_OPTIONS, ANONYMIZATION_OPTIONS — facet chip lists.
- CART_ACTIONS, CART_ACTIONS_READONLY — cart step button definitions.
- SEARCH_APP_PAYLOAD, QUESTION_FORM_PAYLOAD — MCP App interrupt templates.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.graph.subgraphs.request_access.prompts import (
    FORM_SECTION_TITLE_TEMPLATE,
)
from app.service import mcp_search_client

logger = logging.getLogger(__name__)

# Fallback facet chips — used only when the MCP server is unreachable or has
# not been pre-fetched yet. The MCP server is the source of truth: when its
# ``list_facets`` response is cached in ``state.mcp_facet_cache`` these lists
# are ignored.

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


def as_str(value: Any, default: str = "") -> str:
    """@brief Coerce a value to str, or return default when None.

    @param value   Arbitrary value (often from resume payloads).
    @param default String used when value is None.
    @return        str(value) or default.
    """
    if value is None:
        return default
    return str(value)


def normalize_product(product: Any) -> dict[str, Any]:
    """@brief Normalize a search hit or ad-hoc dict into the product shape.

    Ensures keys ``content``, ``metadata`` (id, product_type, domain,
    sensitivity), and ``score`` exist for the product-selection UI.

    @param product Dict from the MCP search server or a loose structure; non-dicts are
                   wrapped as synthetic entries.
    @return        Dict with keys ``content``, ``metadata``, ``score``.
    """
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
    """@brief Map a list of products through normalize_product.

    @param products List of product dicts; non-lists yield an empty list.
    @return         List of normalized product dicts.
    """
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
    """@brief Apply built-in option/action defaults for known UI types.

    For ``facet_selection``, replaces options with DOMAIN_OPTIONS,
    PRODUCT_TYPE_OPTIONS, or ANONYMIZATION_OPTIONS by facet. For
    ``cart_review``, uses CART_ACTIONS. For ``product_selection``, forces
    search and multi-select flags on.

    @param ui_type              Interrupt payload type (e.g. facet_selection).
    @param facet                Facet id when ui_type is facet_selection.
    @param options              Caller-provided options; may be overridden.
    @param actions              Caller-provided actions; may be overridden.
    @param allow_search         Initial allow_search flag.
    @param allow_multi_select   Initial allow_multi_select flag.
    @return Tuple ``(options, actions, allow_search, allow_multi_select)``.
    """
    canonical_options = options
    canonical_actions = actions
    canonical_allow_search = allow_search
    canonical_allow_multi_select = allow_multi_select

    if ui_type == "facet_selection":
        # Caller-provided options (typically sourced from
        # ``state.mcp_facet_cache``) take precedence. Fall back to the
        # hardcoded defaults only if the caller passed nothing.
        if canonical_options is None:
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


async def build_search_products_query(
    *,
    query: str,
    domains: list[str] | None = None,
    anonymization: str | None = None,
    study_id: str | None = None,
    k: int = 8,
) -> list[dict]:
    """@brief Run product search via the MCP search-app server.

    Thin adapter over :func:`app.service.mcp_search_client.search`. Filters
    with empty / ``"all"`` values are dropped before the MCP call so the
    server treats them as "no filter".

    @param query         Free-text search string; ``'*'`` or empty matches all.
    @param domains       Multi-select domain ids; ``None`` / ``[]`` skips.
    @param anonymization Anonymization level id (e.g. ``deidentified``); None skips.
    @param study_id      Clinical study id substring; None / empty skips.
    @param k             Maximum hits to return (client-side cap).
    @return              List of raw product dicts from the MCP server.
    """
    results = await mcp_search_client.search(
        search_text=(query or "").strip() or "*",
        domains=list(domains or []),
        anonymization=(anonymization or None),
        study_id=(study_id or None),
    )
    if k and len(results) > k:
        results = results[:k]
    logger.info(
        "search_products: query=%r domains=%s anon=%s study_id=%s -> %d results",
        query, domains, anonymization, study_id, len(results),
    )
    return results


def facet_options_from_cache(
    state: dict | None, facet: str
) -> list[dict] | None:
    """@brief Pull MCP-sourced facet options for a given facet id.

    Reads from the ``mcp_facet_cache`` field that ``mcp_prefetch_facets``
    populates. Returns ``None`` when the cache is missing or the facet is
    not present — callers should fall through to the hardcoded defaults.

    @param state  The current AppState (or any dict exposing mcp_facet_cache).
    @param facet  Facet id, e.g. ``"domain"`` or ``"anonymization"``.
    @return       List of ``{"id", "label"}`` dicts or ``None``.
    """
    if not isinstance(state, dict):
        return None
    cache = state.get("mcp_facet_cache") or {}
    if not isinstance(cache, dict):
        return None
    # MCP server keys: "domains" (plural) and "anonymization" (singular)
    key_map = {"domain": "domains", "anonymization": "anonymization"}
    key = key_map.get(facet)
    if not key:
        return None
    options = cache.get(key)
    if not isinstance(options, list) or not options:
        return None
    # Accept both already-shaped ``{"id","label"}`` and legacy shapes.
    normalized: list[dict] = []
    for opt in options:
        if isinstance(opt, dict) and "id" in opt:
            normalized.append(
                {"id": str(opt["id"]), "label": str(opt.get("label", opt["id"]))}
            )
    return normalized or None


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
    """@brief Build a structured interrupt payload for the chat frontend.

    Merges canonical options/actions via canonicalize_ui_payload, assigns a
    stable prompt_id when omitted, and normalizes any product list.

    @param ui_type             Payload type (facet_selection, product_selection, etc.).
    @param message             Human-readable prompt shown above the UI.
    @param options             Selectable chips; may be replaced per ui_type/facet.
    @param products            Optional product cards (normalized in output).
    @param actions             Button definitions; may be replaced for cart_review.
    @param facet               Facet id for facet_selection UIs.
    @param allow_search        Whether to expose product search in UI.
    @param allow_multi_select  Whether multi-select is allowed.
    @param step                Workflow step id (RA_STEP_*).
    @param prompt_id           Stable id for resume correlation; UUID if omitted.
    @return                    Dict suitable for interrupt() / pending_prompt.
    """
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
    """@brief Build a minimal per-product form schema for the fill_form step.

    @param products  Normalized product dicts (metadata.id used as product_id).
    @return          List of schema dicts with product_id, title, and fields.
    """
    schema: list[dict] = []
    for p in products:
        meta = p.get("metadata", {}) if isinstance(p, dict) else {}
        pid = meta.get("id", "unknown")
        schema.append(
            {
                "product_id": pid,
                "title": FORM_SECTION_TITLE_TEMPLATE.format(product_id=pid),
                "fields": [
                    {"name": "business_justification", "label": "Business justification", "type": "textarea"},
                    {"name": "data_scope", "label": "Intended data use", "type": "text"},
                ],
            }
        )
    return schema
