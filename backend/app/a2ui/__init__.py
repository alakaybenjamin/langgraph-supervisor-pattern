"""A2UI v0.9 integration package.

Builders and the custom ``datagov.local:v1`` catalog that map our
request-access interrupts onto the A2UI protocol. Import sites go through
:mod:`app.a2ui.builders`; the catalog JSON under ``catalogs/`` is both
served to the browser (see :mod:`app.main`) and consumed by the
``A2uiSchemaManager`` when we eventually prompt an LLM to author surfaces.
"""

from app.a2ui.builders import (
    A2UI_CATALOG_ID,
    A2UI_SURFACE_PREFIX,
    A2UI_VERSION,
    build_facet_selection_surface,
    build_product_selection_surface,
)

__all__ = [
    "A2UI_CATALOG_ID",
    "A2UI_SURFACE_PREFIX",
    "A2UI_VERSION",
    "build_facet_selection_surface",
    "build_product_selection_surface",
]
