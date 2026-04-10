"""
Python MCP App Server for the Question Form.

Serves the same rich UI as the TypeScript version, but with a Python backend.
The client-side HTML/JS/CSS is identical -- built with Vite and served as a
single-file resource.

Usage:
    python server.py             # HTTP on port 3001
    python server.py --stdio     # stdio transport
"""

import asyncio
import sys
from pathlib import Path

from mcp.server.lowlevel import Server
import mcp.types as types

RESOURCE_URI = "ui://question-form/mcp-app.html"
RESOURCE_MIME_TYPE = "text/html;profile=mcp-app"
DIST_DIR = Path(__file__).parent / "dist"

QUESTION_TEMPLATE: dict = {
    "mandatory": [
        {
            "id": "requestFor",
            "text": "Add Other Users",
            "mandatory": False,
            "type": "user-search",
        },
        {
            "id": "analysisDateRange",
            "text": "Analysis Start and End Date",
            "mandatory": True,
            "type": "dateRange",
        },
        {
            "id": "proposalName",
            "text": "What is the Proposal Name?",
            "mandatory": True,
            "type": "text",
            "validation": {"minLength": 3, "maxLength": 200},
        },
        {
            "id": "scientificPurpose",
            "text": "Scientific Purpose of the Request",
            "mandatory": True,
            "type": "textarea",
            "validation": {"minLength": 10},
        },
        {
            "id": "scopeActivity",
            "text": "Scope of the activity",
            "mandatory": True,
            "type": "textarea",
            "validation": {"minLength": 10},
        },
    ],
    "ddf": [
        {
            "id": "userIHDActivity",
            "text": "Who will perform the IHD activity?",
            "mandatory": True,
            "type": "multiSelect",
            "options": ["Internal", "External by a third party"],
        },
        {
            "id": "roles",
            "text": "Roles and responsibilities of those involved",
            "mandatory": True,
            "type": "textarea",
            "validation": {"minLength": 10},
        },
        {
            "id": "typeActivity",
            "text": "Types of IHD source this request includes",
            "mandatory": True,
            "type": "multiSelect",
            "options": [
                {
                    "text": "GSK IHD Sources",
                    "info": "<p>Includes:</p><ul><li>Ongoing GSK-sponsored clinical studies where IHD activity is out of scope of the original protocol</li><li>Completed GSK-sponsored clinical studies</li><li>Ongoing or completed Supported Collaborative Studies (SCS) or Investigator Sponsored Studies (ISS)</li><li>Studies acquired through in-licensing or company acquisitions</li><li>Pharmacovigilance data</li></ul>",
                },
                {
                    "text": "External",
                    "info": "<ul><li>Publicly available IHD</li><li>Third-party IHD</li></ul>",
                },
            ],
        },
        {
            "id": "versionICF",
            "text": "Version of protocol / Version of ICF",
            "mandatory": True,
            "type": "textarea",
            "validation": {"minLength": 10},
            "info": "<p>Please include the latest version number for the study protocol or ICF.</p>",
        },
        {
            "id": "sectionICF",
            "text": "Section of protocol / Section of ICF",
            "mandatory": True,
            "type": "textarea",
            "validation": {"minLength": 10},
            "info": "<p>Please include the section of the study protocol or ICF that the proposed activity relates to.</p>",
        },
        {
            "id": "utilized",
            "text": "Can anonymized data be utilized for your analysis?",
            "mandatory": True,
            "type": "select",
            "options": ["Yes", "No"],
            "allowOther": True,
            "info": "<p><strong>Anonymization</strong> refers to the processing of personal information (PI) so that individuals cannot be identified by any reasonable means.</p><p>For most research purposes, anonymization has minimal impact on data usability.</p>",
        },
        {
            "id": "regulated",
            "text": "Is this a regulatory request?",
            "mandatory": True,
            "type": "select",
            "options": ["Yes", "No"],
            "info": "<ul><li>Regulatory requests</li><li>Safety requests for DSUR or PSUR generation</li><li>Reimbursement requests</li></ul>",
        },
        {
            "id": "evaluation",
            "text": "Is evaluation related to a GSK product?",
            "mandatory": True,
            "type": "select",
            "options": ["Yes", "No"],
        },
        {
            "id": "completeSubset",
            "text": "Is this request for complete study data or a subset?",
            "mandatory": True,
            "type": "select",
            "options": ["Complete", "Subset"],
            "info": "<p>Select <strong>Complete</strong> if you require all available study data.</p><p>Select <strong>Subset</strong> if you require specific parts only.</p>",
        },
        {
            "id": "purposeCriteria",
            "text": "If your request includes GSK IHD sources, please select which criteria apply",
            "mandatory": True,
            "type": "multiSelect",
            "options": [
                "Carry out this study and meet the study purpose",
                "Understand the results of this study",
                "Bring the study drug/vaccine to market and support reimbursement",
                "Satisfy regulatory requirements",
                "Develop diagnostic tests to support use of the study drug/vaccine",
                "Ensure the quality of the tests used for the study",
                "Ensure the quality of the tests used for the study drug/vaccine or disease is maintained over time",
                "Develop and improve tests related to the study drug/vaccine or disease",
                "Design additional studies relating to the study drug/vaccine, study disease and related conditions",
                "Support clinical study processes",
                "Publish results of the study",
                "Foster clinical trial diversity in ethnic groups",
                "My request includes GSK IHD sources, but none of the above criteria apply",
                "My request includes GSK IHD sources, but I am not sure if any of the above criteria apply",
                "My request only includes external IHD sources",
            ],
        },
        {
            "id": "legitimatePurpose",
            "text": "Specific and legitimate purpose of the activity",
            "mandatory": True,
            "type": "textarea",
            "validation": {"minLength": 10},
            "info": "<p>For regulatory, safety, or reimbursement-related requests, provide details.</p>",
        },
        {
            "id": "activityType",
            "text": "Type of activity to be performed",
            "mandatory": True,
            "type": "textarea",
            "validation": {"minLength": 10},
        },
        {
            "id": "dataDescription",
            "text": "Broad description of the data to be used and rationale where anonymized IHD cannot be used",
            "mandatory": True,
            "type": "textarea",
            "validation": {"minLength": 10},
        },
        {
            "id": "linksToPlan",
            "text": "Links to other plans (e.g., asset plans, publication plans)",
            "mandatory": True,
            "type": "text",
        },
        {
            "id": "reporting",
            "text": "Details on reporting, disclosure, and close-out activities required",
            "mandatory": True,
            "type": "textarea",
            "info": "<p>Include the final intent of the IHD activity, long-term data management and retention needs.</p>",
        },
        {
            "id": "futureReuse",
            "text": "Considerations for future data re-use",
            "mandatory": True,
            "type": "textarea",
            "validation": {"minLength": 10},
        },
        {
            "id": "useReuseCategory",
            "text": "Is the request for use or reuse?",
            "mandatory": True,
            "type": "select",
            "options": [
                "Study Use",
                "Further Use Related",
                "Further Use Not Related",
            ],
            "info": "<p><strong>Study Use</strong>: Primary use as defined in the study protocol or ICF.</p><p><strong>Further Use Related</strong>: Secondary use related to the study.</p><p><strong>Further Use Not Related</strong>: Secondary use unrelated to the original study.</p>",
        },
    ],
    "default": [
        {
            "id": "ihdActivityProposalText",
            "text": "Completed IHD Activity Proposal (Text)",
            "mandatory": True,
            "type": "textarea",
            "validation": {"minLength": 10},
        },
        {
            "id": "ihdActivityProposalFile",
            "text": "Completed IHD Activity Proposal (File)",
            "mandatory": False,
            "type": "file",
            "fileTypes": ["docx"],
            "maxFiles": 1,
            "maxFileSizeMB": 10,
        },
    ],
    "onyx": [
        {
            "id": "userIHDActivity",
            "text": "Who will perform the IHD activity?",
            "mandatory": True,
            "type": "multiSelect",
            "options": ["Internal", "External by a third party"],
        },
    ],
    "productSpecific": {},
}


def create_server() -> Server:
    server = Server("Question Form App Server")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        tool = types.Tool.model_validate(
            {
                "name": "open-question-form",
                "description": (
                    "Opens an interactive question form with multiple sections "
                    "(Mandatory, DDF, Default, Onyx). Each section contains fields "
                    "with appropriate controls like text inputs, textareas, date pickers, "
                    "dropdowns, multi-selects, and file uploads."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "section": {
                            "type": "string",
                            "enum": [
                                "all",
                                "mandatory",
                                "ddf",
                                "default",
                                "onyx",
                            ],
                            "description": "Which section to display. Defaults to 'all'.",
                        }
                    },
                },
                "_meta": {
                    "ui": {"resourceUri": RESOURCE_URI},
                    "ui/resourceUri": RESOURCE_URI,
                },
            }
        )
        return [tool]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> types.CallToolResult:
        if name != "open-question-form":
            raise ValueError(f"Unknown tool: {name}")

        section = (arguments or {}).get("section", "all")

        if section == "all":
            template_data = QUESTION_TEMPLATE
        else:
            template_data = {section: QUESTION_TEMPLATE.get(section, [])}

        section_names = list(template_data.keys())
        total_fields = sum(
            len(v) for v in template_data.values() if isinstance(v, list)
        )

        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=(
                        f"Question form loaded with {len(section_names)} section(s) "
                        f"and {total_fields} field(s). Sections: {', '.join(section_names)}"
                    ),
                )
            ],
            structuredContent={
                "template": template_data,
                "section": section,
            },
        )

    @server.list_resources()
    async def handle_list_resources() -> list[types.Resource]:
        return [
            types.Resource(
                uri=RESOURCE_URI,
                name="Question Form UI",
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


async def run_http(port: int = 3001):
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
        port = 3001
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg == "--port" and i < len(sys.argv) - 1:
                port = int(sys.argv[i + 1])
        await run_http(port)


if __name__ == "__main__":
    asyncio.run(main())
