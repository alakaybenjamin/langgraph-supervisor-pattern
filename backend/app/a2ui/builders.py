"""@file builders.py
@brief A2UI v0.9 message builders for the request-access interrupts.

Each builder returns a single dict that slots into the existing
``interrupt_value`` contract. The shape is intentionally a discriminated
union extension (``type: "a2ui"``) rather than a replacement so that the
feature flag in :mod:`app.core.config` can flip individual interrupt
types between the legacy and A2UI paths without changing any resume
routing logic in :func:`app.graph.subgraphs.request_access.graph._apply_structured_answer`.

Design invariant
----------------
The frontend A2UI ``actionHandler`` MUST translate the actions emitted by
these surfaces back into the exact ``resume_data`` shape the legacy
interrupts produced. The ``resume_hint`` block we include in every
payload is how the frontend knows which legacy shape to mint. See
``frontend/client/src/app/core/services/chat.service.ts::handleA2uiAction``.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping

A2UI_VERSION = "v0.9"
A2UI_CATALOG_ID = "datagov.local:v1"
A2UI_SURFACE_PREFIX = "datagov/"


def _surface_id(prompt_id: str | None) -> str:
    """@brief Derive a stable surface id from a prompt id (or mint one).

    A2UI requires every ``createSurface`` to name a surface; we key ours
    by ``prompt_id`` so the frontend can idempotently receive the same
    interrupt without creating duplicate surfaces.
    """
    return f"{A2UI_SURFACE_PREFIX}{prompt_id or uuid.uuid4()}"


def _envelope(message: Mapping[str, Any]) -> dict[str, Any]:
    """@brief Wrap a raw A2UI body (createSurface / updateComponents / ...) with the v0.9 ``version`` tag."""
    return {"version": A2UI_VERSION, **message}


def build_facet_selection_surface(
    *,
    step: str,
    prompt: str,
    facet: str,
    options: list[dict[str, Any]],
    prompt_id: str | None = None,
) -> dict[str, Any]:
    """@brief Build an A2UI interrupt payload for a facet-selection question.

    Produces three A2UI v0.9 messages (``createSurface`` + ``updateDataModel``
    + ``updateComponents``). The ``FacetChipRow`` component is defined by
    our custom catalog (``backend/app/a2ui/catalogs/datagov-v1.json``) and
    implemented by ``FacetChipRowComponent`` on the Angular side.

    @param step       Workflow step id (``RA_STEP_*``).
    @param prompt     Human-readable prompt shown above the chip row.
    @param facet      Facet id (``domain`` / ``product_type`` / ``anonymization``).
    @param options    List of ``{id, label}`` chip dicts.
    @param prompt_id  Stable id for resume correlation; a UUID is minted
                      when the caller doesn't provide one.
    @return           Interrupt payload with ``type == "a2ui"``.
    """
    pid = prompt_id or str(uuid.uuid4())
    surface_id = _surface_id(pid)

    create_surface = _envelope(
        {
            "createSurface": {
                "surfaceId": surface_id,
                "catalogId": A2UI_CATALOG_ID,
            }
        }
    )
    # NB: ``prompt`` is intentionally NOT in the data model. The chat
    # bubble shown by ``MessageComponent`` already renders the prompt
    # (with markdown) via the top-level ``message`` field below, so
    # putting it on the surface too would double-render it. The
    # FacetChipRow catalog schema keeps ``prompt`` optional precisely
    # for this case — host-driven flows where the bubble owns the text.
    update_data_model = _envelope(
        {
            "updateDataModel": {
                "surfaceId": surface_id,
                "path": "/",
                "value": {
                    "facet": facet,
                    "options": list(options or []),
                },
            }
        }
    )
    update_components = _envelope(
        {
            "updateComponents": {
                "surfaceId": surface_id,
                "components": [
                    {
                        "id": "root",
                        "component": "FacetChipRow",
                        "facet": facet,
                        "options": {"path": "/options"},
                        "onSelect": {
                            "event": {
                                "name": "facet.select",
                                "context": {
                                    "facet": facet,
                                    "step": step,
                                    "prompt_id": pid,
                                },
                            }
                        },
                    }
                ],
            }
        }
    )

    return {
        "type": "a2ui",
        # Top-level ``message`` is the source of truth for the chat
        # bubble. ``ChatService.setInterruptMessage`` reads this; without
        # it the UI falls back to a generic "Please complete the action
        # in the panel." placeholder.
        "message": prompt,
        "step": step,
        "prompt_id": pid,
        "surface_id": surface_id,
        "catalog_id": A2UI_CATALOG_ID,
        # Routing hint consumed by ChatService.handleA2uiAction on the frontend.
        # Keeping it inside the payload (rather than baking it into the event
        # name) lets the LLM-authored flows in a later phase override the
        # destination without touching the catalog schema.
        "resume_hint": {"ui_type": "facet_selection", "facet": facet},
        "a2ui_messages": [create_surface, update_data_model, update_components],
    }


def build_product_selection_surface(
    *,
    step: str,
    prompt: str,
    products: list[dict[str, Any]],
    prompt_id: str | None = None,
) -> dict[str, Any]:
    """@brief Build an A2UI interrupt payload for the product-selection step.

    Three actions are wired onto the ``ProductPicker`` component, each
    mapped back to the legacy ``resume_data`` shape by
    ``ChatService.handleA2uiAction``:

    - ``product.confirm`` → ``{action: "select", products: [...]}``
    - ``product.open_search`` → ``{action: "open_search"}``
    - ``product.refine`` → ``{action: "refine_filters"}``

    Selection state is intentionally NOT in the data model — the
    renderer owns it and only emits the final picks on confirm. This
    matches the legacy MessageComponent behaviour and avoids a
    server round-trip per checkbox click.

    @param step       Workflow step id (``RA_STEP_CHOOSE_PRODUCTS``).
    @param prompt     Human-readable prompt shown above the cards;
                      surfaced through the chat bubble's ``message``
                      field, not rendered by the surface itself.
    @param products   Normalized product dicts (see ``normalize_products``).
    @param prompt_id  Stable id for resume correlation; UUID if omitted.
    @return           Interrupt payload with ``type == "a2ui"``.
    """
    pid = prompt_id or str(uuid.uuid4())
    surface_id = _surface_id(pid)

    create_surface = _envelope(
        {
            "createSurface": {
                "surfaceId": surface_id,
                "catalogId": A2UI_CATALOG_ID,
            }
        }
    )
    update_data_model = _envelope(
        {
            "updateDataModel": {
                "surfaceId": surface_id,
                "path": "/",
                "value": {
                    "products": list(products or []),
                },
            }
        }
    )

    # Common context block tagged onto every action so the resume hint,
    # step, and prompt id ride along with the user-fired event. The
    # frontend dispatcher merges ``value`` (toggle) or ``products``
    # (confirm) on top at dispatch time.
    base_context = {
        "step": step,
        "prompt_id": pid,
    }
    update_components = _envelope(
        {
            "updateComponents": {
                "surfaceId": surface_id,
                "components": [
                    {
                        "id": "root",
                        "component": "ProductPicker",
                        "products": {"path": "/products"},
                        "confirmLabelTemplate": "Add {count} to Request",
                        "onToggle": {
                            "event": {
                                "name": "product.toggle",
                                "context": base_context,
                            }
                        },
                        "onConfirm": {
                            "event": {
                                "name": "product.confirm",
                                "context": base_context,
                            }
                        },
                        "onOpenSearch": {
                            "event": {
                                "name": "product.open_search",
                                "context": base_context,
                            }
                        },
                        "onRefine": {
                            "event": {
                                "name": "product.refine",
                                "context": base_context,
                            }
                        },
                    }
                ],
            }
        }
    )

    return {
        "type": "a2ui",
        "message": prompt,
        "step": step,
        "prompt_id": pid,
        "surface_id": surface_id,
        "catalog_id": A2UI_CATALOG_ID,
        "resume_hint": {"ui_type": "product_selection"},
        "a2ui_messages": [create_surface, update_data_model, update_components],
    }
