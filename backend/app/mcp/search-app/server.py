"""
Python MCP App Server for Data Product Search.

This server exposes three MCP tools:

1. ``search-data-products`` *(UI-backed)* — opens the interactive search iframe
   with pre-applied filters. Kept for the in-chat MCP App experience.
2. ``search`` *(headless)* — backend-callable search that takes a free-text
   query plus an optional ``filters`` object (multi-select ``domains``, single
   ``anonymization`` level, and an optional free-text ``study_id``). Returns
   the result list in ``structuredContent`` — no UI involved.
3. ``list_facets`` *(headless)* — returns the canonical facet chips
   (``domains`` and ``anonymization``) so callers can render filter UIs with
   labels that match this server's expected input-value ids.

Treat this server as a third-party data catalog: the request-access workflow
in the main app only talks to it over MCP and has no access to the underlying
storage.

Usage:
    python server.py             # HTTP on port 3002
    python server.py --stdio     # stdio transport
"""

import asyncio
import sys
from pathlib import Path

from mcp.server.lowlevel import Server
import mcp.types as types

RESOURCE_URI = "ui://search-app/mcp-app.html"
RESOURCE_MIME_TYPE = "text/html;profile=mcp-app"
DIST_DIR = Path(__file__).parent / "dist"

SAMPLE_PRODUCTS = [
    {
        "id": "dp-001",
        "title": "Patient Demographics Dataset",
        "description": "Anonymized patient demographic information including age ranges, geographic regions, and visit frequency across multiple studies.",
        "domain": "r_and_d",
        "product_type": "default",
        "sensitivity": "high",
        "anonymization": "deidentified",
        "study_id": "STU-203121",
        "owner": "Clinical Data Management",
    },
    {
        "id": "dp-002",
        "title": "Clinical Trial Results - Phase III",
        "description": "Phase III trial outcomes for cardiovascular treatments, including efficacy and safety endpoints.",
        "domain": "r_and_d",
        "product_type": "ddf",
        "sensitivity": "critical",
        "anonymization": "limited",
        "study_id": "STU-203121",
        "owner": "Clinical Data Management",
    },
    {
        "id": "dp-003",
        "title": "Sales Performance Data",
        "description": "Regional sales performance metrics, market share analysis, and competitive benchmarking data.",
        "domain": "commercial",
        "product_type": "default",
        "sensitivity": "medium",
        "anonymization": "identified",
        "study_id": None,
        "owner": "Commercial Analytics",
    },
    {
        "id": "dp-004",
        "title": "Drug Safety Reports",
        "description": "Post-marketing surveillance data including adverse event reports and safety signal analysis.",
        "domain": "safety",
        "product_type": "ddf",
        "sensitivity": "critical",
        "anonymization": "limited",
        "study_id": "STU-401052",
        "owner": "Pharmacovigilance",
    },
    {
        "id": "dp-005",
        "title": "Manufacturing Quality Metrics",
        "description": "Batch quality data, deviation reports, and process control metrics across manufacturing sites.",
        "domain": "operations",
        "product_type": "onyx",
        "sensitivity": "medium",
        "anonymization": "identified",
        "study_id": None,
        "owner": "Quality Assurance",
    },
    {
        "id": "dp-006",
        "title": "Real-World Evidence Dataset",
        "description": "Electronic health records and claims data for real-world outcomes analysis across therapeutic areas.",
        "domain": "r_and_d",
        "product_type": "ddf",
        "sensitivity": "critical",
        "anonymization": "deidentified",
        "study_id": "STU-558970",
        "owner": "RWE Analytics",
    },
    {
        "id": "dp-007",
        "title": "Regulatory Submission Archive",
        "description": "Compiled regulatory filing data including NDA/BLA submissions and correspondence.",
        "domain": "regulatory",
        "product_type": "default",
        "sensitivity": "high",
        "anonymization": "identified",
        "study_id": None,
        "owner": "Regulatory Affairs",
    },
    {
        "id": "dp-008",
        "title": "Market Access Analytics",
        "description": "Payer landscape analysis, formulary tracking, and reimbursement data across geographies.",
        "domain": "commercial",
        "product_type": "default",
        "sensitivity": "medium",
        "anonymization": "limited",
        "study_id": None,
        "owner": "Market Access Team",
    },
    {
        "id": "dp-009",
        "title": "Genomics Research Data",
        "description": "Whole genome sequencing data and biomarker analysis for precision medicine initiatives.",
        "domain": "r_and_d",
        "product_type": "ddf",
        "sensitivity": "critical",
        "anonymization": "deidentified",
        "study_id": "STU-203121",
        "owner": "Genomics Lab",
    },
    {
        "id": "dp-010",
        "title": "HR Workforce Analytics",
        "description": "Workforce planning data, employee engagement scores, and retention analytics.",
        "domain": "hr",
        "product_type": "default",
        "sensitivity": "high",
        "anonymization": "limited",
        "study_id": None,
        "owner": "People Analytics",
    },
]


ANONYMIZATION_FACET: list[dict[str, str]] = [
    {"id": "identified", "label": "Identified (standard access)"},
    {"id": "limited", "label": "Limited / aggregated"},
    {"id": "deidentified", "label": "De-identified only"},
]


def _get_facets() -> dict:
    domains = sorted({p["domain"] for p in SAMPLE_PRODUCTS})
    product_types = sorted({p["product_type"] for p in SAMPLE_PRODUCTS})
    sensitivities = sorted({p["sensitivity"] for p in SAMPLE_PRODUCTS})
    return {
        "domains": [
            {"id": d, "label": d.replace("_", " ").title()} for d in domains
        ],
        "product_types": [
            {"id": t, "label": t.upper()} for t in product_types
        ],
        "sensitivities": [
            {"id": s, "label": s.title()} for s in sensitivities
        ],
    }


def _search_products(
    query: str = "",
    domain: str = "all",
    product_type: str = "all",
    sensitivity: str = "all",
) -> list[dict]:
    """Legacy search used by the UI-backed ``search-data-products`` tool.

    Signature preserved for the existing in-chat search iframe (which expects
    single-select ``domain``/``product_type``/``sensitivity`` strings).
    """
    results = SAMPLE_PRODUCTS[:]
    if domain and domain != "all":
        results = [p for p in results if p["domain"] == domain]
    if product_type and product_type != "all":
        results = [p for p in results if p["product_type"] == product_type]
    if sensitivity and sensitivity != "all":
        results = [p for p in results if p["sensitivity"] == sensitivity]
    if query:
        q = query.lower()
        results = [
            p for p in results
            if q in p["title"].lower()
            or q in p["description"].lower()
            or q in p["id"].lower()
        ]
    return results


# ---------------------------------------------------------------------------
# Headless search (backend / LangGraph-callable)
# ---------------------------------------------------------------------------


def _list_facets() -> dict:
    """Return canonical facet chips for the headless ``search`` tool."""
    domains = sorted({p["domain"] for p in SAMPLE_PRODUCTS})
    return {
        "domains": [
            {"id": d, "label": d.replace("_", " ").title()} for d in domains
        ],
        "anonymization": list(ANONYMIZATION_FACET),
    }


def _search(
    search_text: str = "*",
    filters: dict | None = None,
) -> list[dict]:
    """Headless search used by the ``search`` MCP tool.

    :param search_text: Free-text query. Use ``"*"`` (or empty) to match all
        products. Matched case-insensitively against title, description, id.
    :param filters: Optional dict with any subset of::

        {
            "domains":       list[str]  # multi-select; empty = no filter
            "anonymization": str        # enum; empty = no filter
            "study_id":      str        # substring match; empty = no filter
        }

    :returns: List of product dicts matching every provided filter.
    """
    filters = filters or {}
    domains = [
        d for d in (filters.get("domains") or []) if d and d != "all"
    ]
    anonymization = (filters.get("anonymization") or "").strip()
    study_id = (filters.get("study_id") or "").strip()

    results = list(SAMPLE_PRODUCTS)
    if domains:
        results = [p for p in results if p.get("domain") in domains]
    if anonymization:
        results = [p for p in results if p.get("anonymization") == anonymization]
    if study_id:
        sid = study_id.lower()
        results = [
            p for p in results if sid in (p.get("study_id") or "").lower()
        ]

    q = (search_text or "").strip()
    if q and q != "*":
        ql = q.lower()
        results = [
            p for p in results
            if ql in p.get("title", "").lower()
            or ql in p.get("description", "").lower()
            or ql in p.get("id", "").lower()
        ]
    return results


def create_server() -> Server:
    server = Server("Search App Server")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        facets = _list_facets()
        domain_ids = [d["id"] for d in facets["domains"]]
        anonymization_ids = [a["id"] for a in facets["anonymization"]]

        ui_tool = types.Tool.model_validate(
            {
                "name": "search-data-products",
                "description": (
                    "Opens an interactive data product search interface with "
                    "faceted filters (domain, type, sensitivity) and free-text search. "
                    "Supports multi-select for adding products to a request."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filters": {
                            "type": "object",
                            "description": "Pre-applied filters",
                            "properties": {
                                "domain": {"type": "string"},
                                "product_type": {"type": "string"},
                                "sensitivity": {"type": "string"},
                            },
                        },
                    },
                },
                "_meta": {
                    "ui": {"resourceUri": RESOURCE_URI},
                    "ui/resourceUri": RESOURCE_URI,
                },
            }
        )

        search_tool = types.Tool.model_validate(
            {
                "name": "search",
                "description": (
                    "Headless search for data products. Returns products matching "
                    "a free-text query and optional filters. Intended for backend / "
                    "LangGraph callers that already have filter values — no UI is "
                    "opened. Pass ``search_text='*'`` (or omit) to match everything."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "search_text": {
                            "type": "string",
                            "description": (
                                "Free-text query. '*' or empty = match all products. "
                                "Matches against product title, description and id."
                            ),
                            "default": "*",
                        },
                        "filters": {
                            "type": "object",
                            "description": (
                                "Optional filter bundle. Omit any key to skip "
                                "that filter; an empty array/empty string is also "
                                "treated as 'no filter'."
                            ),
                            "properties": {
                                "domains": {
                                    "type": "array",
                                    "description": (
                                        "Multi-select list of business domains. "
                                        "Values must come from ``list_facets().domains[*].id``."
                                    ),
                                    "items": {
                                        "type": "string",
                                        "enum": domain_ids,
                                    },
                                },
                                "anonymization": {
                                    "type": "string",
                                    "description": (
                                        "Required anonymization / data-handling level."
                                    ),
                                    "enum": anonymization_ids,
                                },
                                "study_id": {
                                    "type": "string",
                                    "description": (
                                        "Clinical study / trial ID (e.g. 'STU-203121'). "
                                        "Case-insensitive substring match."
                                    ),
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
            }
        )

        list_facets_tool = types.Tool.model_validate(
            {
                "name": "list_facets",
                "description": (
                    "List canonical facet chips for the ``search`` tool: the "
                    "valid ``domains`` and ``anonymization`` values with their "
                    "display labels. Call this before rendering filter UIs so "
                    "the ids match what ``search`` expects."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            }
        )

        return [ui_tool, search_tool, list_facets_tool]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None,
    ) -> types.CallToolResult:
        args = arguments or {}

        if name == "search-data-products":
            filters = args.get("filters") or {}
            domain = filters.get("domain", "all")
            product_type = filters.get("product_type", "all")
            sensitivity = filters.get("sensitivity", "all")

            results = _search_products(
                domain=domain,
                product_type=product_type,
                sensitivity=sensitivity,
            )
            facets = _get_facets()

            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Search loaded with {len(results)} product(s) and {len(facets)} facet groups.",
                    )
                ],
                structuredContent={
                    "products": results,
                    "facets": facets,
                    "appliedFilters": {
                        "domain": domain,
                        "product_type": product_type,
                        "sensitivity": sensitivity,
                    },
                },
            )

        if name == "search":
            search_text = args.get("search_text") or "*"
            filters = args.get("filters") or {}
            results = _search(search_text=search_text, filters=filters)

            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Found {len(results)} product(s).",
                    )
                ],
                structuredContent={
                    "products": results,
                    "total": len(results),
                    "appliedFilters": {
                        "search_text": search_text,
                        "domains": filters.get("domains") or [],
                        "anonymization": filters.get("anonymization"),
                        "study_id": filters.get("study_id"),
                    },
                },
            )

        if name == "list_facets":
            facets = _list_facets()
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=(
                            f"{len(facets['domains'])} domain(s), "
                            f"{len(facets['anonymization'])} anonymization level(s)."
                        ),
                    )
                ],
                structuredContent=facets,
            )

        raise ValueError(f"Unknown tool: {name}")

    @server.list_resources()
    async def handle_list_resources() -> list[types.Resource]:
        return [
            types.Resource(
                uri=RESOURCE_URI,
                name="Data Product Search UI",
                mimeType=RESOURCE_MIME_TYPE,
            )
        ]

    @server.read_resource()
    async def handle_read_resource(uri: types.AnyUrl):
        from mcp.server.lowlevel.server import ReadResourceContents

        if str(uri) == RESOURCE_URI:
            html_path = DIST_DIR / "mcp-app.html"
            if not html_path.exists():
                raise FileNotFoundError(
                    f"Built UI not found at {html_path}. Run 'npm run build' first."
                )
            return [
                ReadResourceContents(
                    content=html_path.read_text(encoding="utf-8"),
                    mime_type=RESOURCE_MIME_TYPE,
                )
            ]
        raise ValueError(f"Unknown resource: {uri}")

    return server


async def run_stdio():
    from mcp.server.stdio import stdio_server

    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


async def run_http(port: int = 3002):
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    import uvicorn

    session_manager = StreamableHTTPSessionManager(
        app=create_server(),
        stateless=True,
        json_response=True,
    )

    CORS_HEADERS: list[tuple[bytes, bytes]] = [
        (b"access-control-allow-origin", b"*"),
        (b"access-control-allow-methods", b"GET, POST, PUT, DELETE, OPTIONS"),
        (b"access-control-allow-headers", b"*"),
        (b"access-control-expose-headers", b"*"),
    ]

    _session_ctx = None

    async def app(scope: dict, receive, send):
        nonlocal _session_ctx

        if scope["type"] == "lifespan":
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    _session_ctx = session_manager.run()
                    await _session_ctx.__aenter__()
                    await send({"type": "lifespan.startup.complete"})
                elif msg["type"] == "lifespan.shutdown":
                    if _session_ctx:
                        await _session_ctx.__aexit__(None, None, None)
                    await send({"type": "lifespan.shutdown.complete"})
                    return

        if scope["type"] != "http":
            return

        path = scope.get("path", "")
        method = scope.get("method", "")

        if path != "/mcp":
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b"Not Found"})
            return

        if method == "OPTIONS":
            await send({"type": "http.response.start", "status": 204, "headers": CORS_HEADERS})
            await send({"type": "http.response.body", "body": b""})
            return

        original_send = send

        async def send_with_cors(message: dict):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(CORS_HEADERS)
                message = {**message, "headers": headers}
            await original_send(message)

        await session_manager.handle_request(scope, receive, send_with_cors)

    print(f"MCP server listening on http://localhost:{port}/mcp")
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    uv_server = uvicorn.Server(config)
    await uv_server.serve()


async def main():
    if "--stdio" in sys.argv:
        await run_stdio()
    else:
        port = 3002
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg == "--port" and i < len(sys.argv) - 1:
                port = int(sys.argv[i + 1])
        await run_http(port)


if __name__ == "__main__":
    asyncio.run(main())
