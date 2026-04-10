# Building MCP Apps: A Complete Guide

An **MCP App** is an interactive HTML/JS user interface that runs inside a sandboxed iframe within an MCP-enabled host (Claude Desktop, a custom chat UI, or any application that supports the MCP Apps protocol). MCP Apps bring rich, interactive experiences — forms, search panels, dashboards, data visualizations — directly into AI conversations, replacing flat text with real UI components.

This guide covers everything needed to build an MCP App from scratch and implement the host-side integration that renders and communicates with it.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [The Two Halves: Server + Client](#2-the-two-halves-server--client)
3. [Part A: Building the MCP Server (Backend)](#3-part-a-building-the-mcp-server-backend)
4. [Part B: Building the MCP App (Client-Side UI)](#4-part-b-building-the-mcp-app-client-side-ui)
5. [Part C: Building the Host](#5-part-c-building-the-host)
6. [The Full Lifecycle: Sequence of Events](#6-the-full-lifecycle-sequence-of-events)
7. [Communication Protocol Reference](#7-communication-protocol-reference)
8. [Build Toolchain](#8-build-toolchain)
9. [Gotchas and Lessons Learned](#9-gotchas-and-lessons-learned)
10. [Appendix: File Structure](#10-appendix-file-structure)

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                        HOST APPLICATION                       │
│  (Claude Desktop, custom chat UI, etc.)                      │
│                                                              │
│  ┌────────────────────┐       ┌────────────────────────────┐ │
│  │    Chat / Agent     │       │     MCP App Panel          │ │
│  │                    │       │  ┌──────────────────────┐  │ │
│  │  "Show me the      │       │  │  <iframe srcdoc>     │  │ │
│  │   search panel"    │──────▶│  │                      │  │ │
│  │                    │       │  │  MCP App (HTML/JS)   │  │ │
│  │                    │       │  │                      │  │ │
│  └────────────────────┘       │  └───────┬──────────────┘  │ │
│                               │          │ postMessage      │ │
│                               │          ▼                  │ │
│                               │   Host Message Handler      │ │
│                               └──────────┬─────────────────┘ │
│                                          │                    │
└──────────────────────────────────────────┼────────────────────┘
                                           │ HTTP (JSON-RPC)
                                           ▼
                              ┌──────────────────────────┐
                              │      MCP SERVER           │
                              │  (Python or Node.js)      │
                              │                          │
                              │  Tool: "search-products" │
                              │  Resource: mcp-app.html  │
                              └──────────────────────────┘
```

An MCP App has three participants:

| Participant | Role | Technology |
|---|---|---|
| **MCP Server** | Serves the HTML UI and handles tool calls that return data | Python (`mcp` SDK) or Node.js (`@modelcontextprotocol/sdk`) |
| **MCP App** (client) | The interactive UI running in a sandboxed iframe | HTML/JS using `@modelcontextprotocol/ext-apps` SDK |
| **Host** | Loads the iframe, brokers messages, forwards tool calls | Any frontend framework (Angular, React, etc.) |

---

## 2. The Two Halves: Server + Client

Every MCP App is a **Tool + Resource** pair registered on the same MCP server:

| Component | MCP Method | Purpose |
|---|---|---|
| **Tool** | `tools/call` | Called by the host/LLM. Returns structured data for the UI. |
| **Resource** | `resources/read` | Returns the bundled HTML file that IS the MCP App UI. |

They are linked together via `_meta.ui.resourceUri` on the tool definition. When a host sees a tool with this metadata, it knows to render the associated resource as an interactive UI rather than displaying plain text.

---

## 3. Part A: Building the MCP Server (Backend)

The MCP server exposes two capabilities: a **tool** and a **resource**. Here is a complete Python example:

### 3.1 Server Skeleton

```python
import asyncio
from pathlib import Path
from mcp.server.lowlevel import Server
import mcp.types as types

RESOURCE_URI = "ui://search-app/mcp-app.html"
RESOURCE_MIME_TYPE = "text/html;profile=mcp-app"
DIST_DIR = Path(__file__).parent / "dist"


def create_server() -> Server:
    server = Server("My App Server")

    # --- Tool Registration ---
    # --- Resource Registration ---

    return server
```

The `RESOURCE_URI` is a custom URI scheme (`ui://`) that acts as a stable identifier linking the tool to its resource. It does not need to be a real URL — it just needs to match between the tool's `_meta` and the resource listing.

The `RESOURCE_MIME_TYPE` **must** be `"text/html;profile=mcp-app"`. This MIME type signals to hosts that this resource is an MCP App.

### 3.2 Registering the Tool

The tool is what the LLM or host calls. It returns two things:
- **`content`**: A text summary for non-UI-capable hosts (plain text fallback).
- **`structuredContent`**: A JSON object that the MCP App UI will consume.

```python
@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool.model_validate({
            "name": "search-data-products",
            "description": "Opens an interactive data product search interface.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "object",
                        "properties": {
                            "domain": {"type": "string"},
                            "product_type": {"type": "string"},
                        },
                    },
                },
            },
            # This is the critical link — it tells the host which resource to render
            "_meta": {
                "ui": {"resourceUri": RESOURCE_URI},
                "ui/resourceUri": RESOURCE_URI,
            },
        })
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> types.CallToolResult:
    filters = (arguments or {}).get("filters", {})

    products = search_products(**filters)  # your business logic
    facets = get_facets()

    return types.CallToolResult(
        # Text fallback for hosts without UI support
        content=[
            types.TextContent(
                type="text",
                text=f"Found {len(products)} product(s).",
            )
        ],
        # Structured data consumed by the MCP App UI
        structuredContent={
            "products": products,
            "facets": facets,
            "appliedFilters": filters,
        },
    )
```

**Key points:**
- `_meta.ui.resourceUri` links this tool to the resource that provides its UI.
- `content` must always be populated — it's the fallback for hosts that don't render MCP Apps.
- `structuredContent` is the rich data payload that only UI-capable hosts use.

### 3.3 Registering the Resource

The resource serves the bundled HTML file:

```python
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
```

The HTML file must be a **single self-contained file** (all CSS and JS inlined). This is because it will be loaded as an iframe `srcdoc` — it cannot reference external scripts or stylesheets.

### 3.4 Running the Server (HTTP Transport)

For integration with web hosts, run via HTTP with Streamable HTTP Session Manager:

```python
async def run_http(port: int = 3001):
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    import uvicorn

    session_manager = StreamableHTTPSessionManager(
        app=create_server(),
        stateless=True,       # Each request gets a new session
        json_response=True,   # Return JSON instead of SSE
    )

    # CORS headers are needed for browser-based hosts
    CORS_HEADERS = [
        (b"access-control-allow-origin", b"*"),
        (b"access-control-allow-methods", b"GET, POST, PUT, DELETE, OPTIONS"),
        (b"access-control-allow-headers", b"*"),
        (b"access-control-expose-headers", b"*"),
    ]

    _session_ctx = None

    async def app(scope, receive, send):
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

        method = scope.get("method", "")
        if method == "OPTIONS":
            await send({"type": "http.response.start", "status": 204, "headers": CORS_HEADERS})
            await send({"type": "http.response.body", "body": b""})
            return

        original_send = send
        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(CORS_HEADERS)
                message = {**message, "headers": headers}
            await original_send(message)

        await session_manager.handle_request(scope, receive, send_with_cors)

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
```

---

## 4. Part B: Building the MCP App (Client-Side UI)

The MCP App is a vanilla HTML/JS (or React/Vue/Svelte) application that uses the `@modelcontextprotocol/ext-apps` SDK to communicate with its host.

### 4.1 HTML Entry Point

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>My MCP App</title>
</head>
<body>
  <div class="main"></div>
  <script type="module" src="./src/mcp-app.ts"></script>
</body>
</html>
```

This is the Vite entry point. After building, everything (CSS, JS, HTML) is inlined into a single file via `vite-plugin-singlefile`.

### 4.2 App Lifecycle (TypeScript)

```typescript
import {
  App,
  applyDocumentTheme,
  applyHostFonts,
  applyHostStyleVariables,
  type McpUiHostContext,
} from "@modelcontextprotocol/ext-apps";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import "./global.css";

// ── State ───────────────────────────────────
let dataLoaded = false;
let products: Product[] = [];

// ── Rendering ───────────────────────────────
function renderApp(): void {
  const main = document.querySelector(".main") as HTMLElement;
  if (!main) return;

  if (!dataLoaded) {
    main.innerHTML = `<div class="loading">Loading...</div>`;
    return;
  }

  // Render your UI using the data from `products`
  main.innerHTML = `
    <h1>${products.length} products found</h1>
    <!-- ... your interactive UI ... -->
  `;
}

// ── Data Loading ────────────────────────────
function loadData(result: CallToolResult): void {
  const structured = result.structuredContent as {
    products?: Product[];
  } | null;

  products = structured?.products ?? [];
  dataLoaded = true;
  renderApp();
}

// ── Host Context (Theme, Fonts) ─────────────
function handleHostContextChanged(ctx: McpUiHostContext): void {
  if (ctx.theme) applyDocumentTheme(ctx.theme);
  if (ctx.styles?.variables) applyHostStyleVariables(ctx.styles.variables);
  if (ctx.styles?.css?.fonts) applyHostFonts(ctx.styles.css.fonts);
}

// ── MCP App Instance ────────────────────────
const mcpApp = new App({ name: "My App", version: "1.0.0" });

// Register ALL handlers BEFORE calling connect()
mcpApp.ontoolresult = (result) => {
  loadData(result);
};

mcpApp.ontoolinput = (params) => {
  // Called when the tool input (arguments) are provided
};

mcpApp.ontoolinputpartial = (params) => {
  // Called during streaming — partial tool arguments
};

mcpApp.ontoolcancelled = (params) => {
  // Called if the tool call was cancelled
};

mcpApp.onteardown = async () => ({});

mcpApp.onerror = console.error;
mcpApp.onhostcontextchanged = handleHostContextChanged;

// Render initial loading state
renderApp();

// Connect to the host (sends ui/initialize, waits for response)
mcpApp.connect().then(() => {
  const ctx = mcpApp.getHostContext();
  if (ctx) handleHostContextChanged(ctx);
});
```

### 4.3 Communicating Back to the Host

The MCP App can send data back to the host (and ultimately to the LLM/agent) through two mechanisms:

#### `sendMessage` — Send a user message to the conversation

```typescript
await mcpApp.sendMessage({
  role: "user",
  content: [
    {
      type: "text",
      text: JSON.stringify({
        action: "select_products",
        selected_products: [{ id: "dp-001" }, { id: "dp-002" }],
      }),
    },
  ],
});
```

#### `updateModelContext` — Update the LLM's context silently

```typescript
await mcpApp.updateModelContext({
  content: [
    {
      type: "text",
      text: "## User selected 3 data products for access request",
    },
  ],
});
```

### 4.4 Handler Summary

| Handler | Direction | When |
|---|---|---|
| `ontoolresult` | Host → App | Tool call completed; result delivered to the UI |
| `ontoolinput` | Host → App | Tool input arguments provided |
| `ontoolinputpartial` | Host → App | Streaming: partial tool arguments arriving |
| `ontoolcancelled` | Host → App | Tool call was cancelled |
| `onhostcontextchanged` | Host → App | Theme, fonts, display mode, or safe area changed |
| `onteardown` | Host → App | App is being destroyed; clean up resources |
| `onerror` | App internal | SDK-level error |
| `sendMessage()` | App → Host | Send a message to the conversation |
| `updateModelContext()` | App → Host | Silently update LLM context |
| `sendLog()` | App → Host | Send debug log to host |

---

## 5. Part C: Building the Host

The host is the application that renders the MCP App iframe, brokers JSON-RPC messages via `postMessage`, and proxies tool calls to the MCP server.

### 5.1 Loading the App

The host loads the app in three steps:

```
1. Fetch HTML via resources/read
2. Set iframe srcdoc
3. Listen for postMessage from iframe
```

#### Step 1: Fetch the HTML from the MCP server

```typescript
async fetchAppHtml(resourceUri: string, endpoint: string): Promise<string> {
  const body = {
    jsonrpc: "2.0",
    id: 1,
    method: "resources/read",
    params: { uri: resourceUri },
  };
  const resp = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  const json = await resp.json();
  return json.result.contents[0].text;
}
```

#### Step 2: Render in a sandboxed iframe

```html
<iframe
  #mcpFrame
  sandbox="allow-scripts allow-same-origin"
  [srcdoc]="html"
></iframe>
```

The `sandbox` attribute is critical:
- `allow-scripts` — the app needs JavaScript to run
- `allow-same-origin` — needed for `postMessage` communication

#### Step 3: Listen for messages from the iframe

```typescript
window.addEventListener("message", (event) => {
  const data = event.data;
  if (!data || data.jsonrpc !== "2.0") return;

  const iframe = document.querySelector("iframe");
  if (event.source !== iframe?.contentWindow) return;

  if (data.method && data.id != null) {
    handleRequest(data, iframe);     // JSON-RPC request
  } else if (data.method && data.id == null) {
    handleNotification(data);        // JSON-RPC notification
  }
});
```

### 5.2 Handling Requests from the App

The MCP App SDK sends JSON-RPC requests to the host via `postMessage`. The host must respond to each one:

```typescript
function handleRequest(msg, iframe) {
  const respond = (result) => {
    iframe.contentWindow.postMessage(
      { jsonrpc: "2.0", id: msg.id, result },
      "*"
    );
  };

  switch (msg.method) {
    case "ui/initialize":
      respond({
        protocolVersion: "2026-01-26",
        hostInfo: { name: "MyHost", version: "1.0.0" },
        hostCapabilities: {
          updateModelContext: { text: {} },
          message: { text: {} },
        },
        hostContext: {
          theme: "light",
          displayMode: "inline",
        },
      });
      break;

    case "ui/update-model-context":
      respond({});
      // Optionally update the LLM context
      break;

    case "ui/message":
      respond({});
      handleAppMessage(msg.params);
      break;

    case "ui/open-link":
      respond({ isError: false });
      break;

    case "ui/request-display-mode":
      respond({ mode: "inline" });
      break;

    case "ui/resource-teardown":
      respond({});
      break;

    case "ping":
      respond({});
      break;

    case "tools/call":
      // Proxy tool calls to the MCP server (see 5.4)
      handleToolCall(msg, iframe);
      break;

    default:
      respond({});
      break;
  }
}
```

### 5.3 Handling Notifications from the App

Notifications are fire-and-forget messages (no `id` field):

```typescript
function handleNotification(msg) {
  switch (msg.method) {
    case "ui/notifications/initialized":
      // App is ready — now send the tool result
      sendToolResultToApp();
      break;

    case "ui/notifications/size-changed":
      // App wants to resize
      break;

    case "ui/notifications/request-teardown":
      // App wants to close itself
      closePanel();
      break;
  }
}
```

### 5.4 Sending the Tool Result to the App

After the app sends `ui/notifications/initialized`, the host must deliver the tool result. This involves two steps: calling the MCP server's tool, then forwarding the result to the iframe.

```typescript
async function sendToolResultToApp() {
  // 1. Call the MCP server's tool via HTTP
  const body = {
    jsonrpc: "2.0",
    id: 2,
    method: "tools/call",
    params: {
      name: "search-data-products",
      arguments: { filters: { domain: "all" } },
    },
  };
  const resp = await fetch("/mcp/search-app", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const json = await resp.json();
  const result = json.result; // { content: [...], structuredContent: {...} }

  // 2. Forward the result to the iframe via postMessage
  iframe.contentWindow.postMessage(
    {
      jsonrpc: "2.0",
      method: "ui/notifications/tool-result",
      params: result,
    },
    "*"
  );
}
```

### 5.5 Proxying App-Initiated Tool Calls

The MCP App can call tools directly (e.g., to refresh data with new filters). The host proxies these to the MCP server:

```typescript
async function handleToolCall(msg, iframe) {
  try {
    const body = {
      jsonrpc: "2.0",
      id: 99,
      method: "tools/call",
      params: { name: msg.params.name, arguments: msg.params.arguments },
    };
    const resp = await fetch("/mcp/search-app", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const json = await resp.json();

    iframe.contentWindow.postMessage(
      { jsonrpc: "2.0", id: msg.id, result: json.result },
      "*"
    );
  } catch (e) {
    iframe.contentWindow.postMessage(
      {
        jsonrpc: "2.0",
        id: msg.id,
        error: { code: -32603, message: "Tool call failed" },
      },
      "*"
    );
  }
}
```

---

## 6. The Full Lifecycle: Sequence of Events

Here is the complete flow from trigger to user interaction:

```
       HOST                                    IFRAME (MCP App)                  MCP SERVER
        │                                           │                               │
   1.   │── POST resources/read ───────────────────────────────────────────────────▶│
        │◀─ { result: { contents: [{ text: "<html>..." }] } } ────────────────────│
        │                                           │                               │
   2.   │── set iframe srcdoc ────────────────────▶│                               │
        │                                           │── renders, runs JS ──▶       │
        │                                           │                               │
   3.   │◀── postMessage: ui/initialize ───────────│                               │
        │── postMessage: { id, result: {           │                               │
        │     protocolVersion, hostInfo,            │                               │
        │     hostCapabilities, hostContext } } ──▶│                               │
        │                                           │                               │
   4.   │◀── postMessage: ui/notifications/        │                               │
        │    initialized ──────────────────────────│                               │
        │                                           │                               │
   5.   │── POST tools/call ──────────────────────────────────────────────────────▶│
        │◀─ { result: { content, structuredContent } } ───────────────────────────│
        │                                           │                               │
   6.   │── postMessage: ui/notifications/         │                               │
        │   tool-result { params: result } ───────▶│                               │
        │                                           │── ontoolresult fires          │
        │                                           │── renders UI with data        │
        │                                           │                               │
   7.   │                                           │── User interacts ──▶         │
        │                                           │                               │
   8.   │◀── postMessage: ui/message ──────────────│                               │
        │── postMessage: { id, result: {} } ──────▶│                               │
        │                                           │                               │
   9.   │── processes app message ──▶              │                               │
        │   (resume agent, update chat, etc.)       │                               │
```

### Step-by-step:

1. **Host fetches the HTML** by calling `resources/read` on the MCP server.
2. **Host renders the iframe** with the HTML as `srcdoc`.
3. **App initializes** — the SDK sends `ui/initialize` (a JSON-RPC request with an `id`). The host responds with protocol version, capabilities, and context.
4. **App signals ready** — sends `ui/notifications/initialized` (a notification, no `id`).
5. **Host calls the tool** on the MCP server via HTTP to get the data.
6. **Host delivers the tool result** to the iframe via `postMessage` as a `ui/notifications/tool-result` notification.
7. **User interacts** with the UI (clicks, types, selects, etc.).
8. **App sends results back** via `ui/message` (a request with an `id`). The host acknowledges.
9. **Host processes the message** — e.g., resumes an agent graph, updates the chat, closes the panel.

---

## 7. Communication Protocol Reference

All communication between host and app uses **JSON-RPC 2.0** over `postMessage`.

### Message Types

| Type | Has `id`? | Has `method`? | Direction |
|---|---|---|---|
| **Request** | Yes | Yes | Both directions |
| **Response** | Yes (matches request) | No | Both directions |
| **Notification** | No | Yes | Both directions |

### Requests (App → Host)

| Method | Purpose | Response |
|---|---|---|
| `ui/initialize` | App handshake; first message sent | `{ protocolVersion, hostInfo, hostCapabilities, hostContext }` |
| `ui/message` | Send a user message to the conversation | `{}` |
| `ui/update-model-context` | Silently update LLM context | `{}` |
| `ui/open-link` | Open a URL in the user's browser | `{ isError: boolean }` |
| `ui/download-file` | Request a file download | `{ isError: boolean }` |
| `ui/request-display-mode` | Request fullscreen or inline mode | `{ mode: string }` |
| `ui/resource-teardown` | App is cleaning up | `{}` |
| `tools/call` | Call a tool on the MCP server | `{ content, structuredContent }` |
| `ping` | Keepalive | `{}` |

### Notifications (App → Host)

| Method | Purpose |
|---|---|
| `ui/notifications/initialized` | App is ready to receive data |
| `ui/notifications/size-changed` | App wants to resize |
| `ui/notifications/request-teardown` | App wants to close |

### Notifications (Host → App)

| Method | Purpose |
|---|---|
| `ui/notifications/tool-result` | Delivers the `CallToolResult` to the app |
| `ui/notifications/tool-input` | Delivers tool input arguments |
| `ui/notifications/tool-input-partial` | Streaming: partial tool arguments |
| `ui/notifications/tool-cancelled` | Tool call was cancelled |
| `ui/notifications/host-context-changed` | Theme/display mode changed |
| `ui/notifications/request-teardown` | Host is tearing down the app |

---

## 8. Build Toolchain

MCP Apps must be **single self-contained HTML files** because they are loaded as `srcdoc` in an iframe. Use Vite with `vite-plugin-singlefile` to inline all JS and CSS.

### package.json

```json
{
  "name": "my-mcp-app-ui",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "cross-env INPUT=mcp-app.html vite build",
    "watch": "cross-env INPUT=mcp-app.html vite build --watch"
  },
  "dependencies": {
    "@modelcontextprotocol/ext-apps": "^1.0.0"
  },
  "devDependencies": {
    "cross-env": "^10.1.0",
    "typescript": "^5.9.3",
    "vite": "^6.0.0",
    "vite-plugin-singlefile": "^2.3.0"
  }
}
```

### vite.config.ts

```typescript
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

export default defineConfig({
  plugins: [viteSingleFile()],
  build: {
    rollupOptions: {
      input: process.env.INPUT,
    },
    outDir: "dist",
    emptyOutDir: false,
  },
});
```

### Build output

```
src/mcp-app.ts + mcp-app.html + src/global.css
                    │
                    ▼  vite build + vite-plugin-singlefile
                    │
              dist/mcp-app.html    (single file, ~40-150 KB)
```

The Python MCP server reads `dist/mcp-app.html` and returns it via `resources/read`.

---

## 9. Gotchas and Lessons Learned

### 9.1 `allProducts.length === 0` is Not a Loading Indicator

If your tool can return 0 results, you **must** use a separate `dataLoaded` boolean flag to distinguish "haven't received data yet" from "received data but it's empty":

```typescript
// BAD — stalls on empty results
if (items.length === 0) {
  showLoadingSpinner();
}

// GOOD — separate flag
let dataLoaded = false;

if (!dataLoaded) {
  showLoadingSpinner();
} else if (items.length === 0) {
  showEmptyState();
}
```

### 9.2 Always Provide a Text Fallback in `content`

Non-UI-capable hosts (e.g., CLI tools, API clients) ignore `structuredContent` and only see `content`. Always include a meaningful text summary:

```python
return types.CallToolResult(
    content=[types.TextContent(type="text", text=f"Found {len(results)} items.")],
    structuredContent={"items": results},
)
```

### 9.3 Register All Handlers Before `connect()`

The SDK fires events immediately after connecting. If handlers aren't registered, events are lost:

```typescript
// WRONG — handler registered too late
mcpApp.connect();
mcpApp.ontoolresult = (r) => loadData(r);  // May miss the event!

// CORRECT
mcpApp.ontoolresult = (r) => loadData(r);
mcpApp.connect();
```

### 9.4 iframe ViewChild Race Condition

In frameworks like Angular, the `@ViewChild` reference to the iframe may not be available immediately after rendering. The iframe's `ui/initialize` message can arrive before the framework's change detection resolves the element reference. Use a retry/polling approach:

```typescript
private waitForIframe(retries = 20, delayMs = 50): Promise<HTMLIFrameElement | null> {
  return new Promise((resolve) => {
    const check = (attempt: number) => {
      const el = this.iframeRef?.nativeElement;
      if (el?.contentWindow) {
        resolve(el);
      } else if (attempt < retries) {
        setTimeout(() => check(attempt + 1), delayMs);
      } else {
        resolve(null);
      }
    };
    check(0);
  });
}
```

### 9.5 CORS Headers Are Required

Browser-based hosts make HTTP requests to the MCP server from a different origin. The server must include CORS headers on all responses, including `OPTIONS` preflight.

### 9.6 `structuredContent` Must Be Serializable

The `structuredContent` field passes through JSON serialization (HTTP) and `postMessage` (iframe boundary). Ensure all values are plain JSON-serializable objects — no class instances, functions, `Date` objects, or circular references.

### 9.7 Single-File Constraint

The HTML served by `resources/read` must be entirely self-contained. External `<script src="...">` or `<link href="...">` tags will fail because the iframe uses `srcdoc` and has no base URL. Use `vite-plugin-singlefile` to inline everything at build time.

---

## 10. Appendix: File Structure

A typical MCP App project with a Python server:

```
my-mcp-app/
├── server.py                 # Python MCP server (tool + resource handlers)
├── mcp-app.html              # Vite entry point (HTML shell)
├── src/
│   ├── mcp-app.ts            # Client-side app logic + SDK lifecycle
│   └── global.css            # Styles
├── dist/
│   └── mcp-app.html          # Built single-file output (served by server.py)
├── package.json              # Node dependencies (ext-apps SDK, Vite)
├── vite.config.ts            # Vite config with singlefile plugin
└── tsconfig.json             # TypeScript config
```

The server can also be written in Node.js/TypeScript using `@modelcontextprotocol/sdk` with `registerAppTool` and `registerAppResource` helpers from `@modelcontextprotocol/ext-apps/server`.

### Embedding in a Larger Backend

When embedding MCP servers within a larger application (e.g., a FastAPI backend), use a registry pattern that dynamically loads and mounts multiple MCP servers:

```python
# registry.py
MCP_APPS = [
    {"name": "question-form", "folder": "question-form-app-python"},
    {"name": "search-app",    "folder": "search-app"},
]

async def startup_mcp_servers():
    for app_def in MCP_APPS:
        server = load_server_module(app_def["folder"])
        manager = StreamableHTTPSessionManager(
            app=server, stateless=True, json_response=True,
        )
        ctx = manager.run()
        await ctx.__aenter__()
        servers[app_def["name"]] = manager

def mount_mcp_servers(app: FastAPI):
    # Mount each server at /mcp/{name}
    # Rewrite incoming path to /mcp for the session manager
    ...
```

This allows a single backend to host multiple MCP Apps, each at their own endpoint (`/mcp/question-form`, `/mcp/search-app`), while sharing the same HTTP server and port.
