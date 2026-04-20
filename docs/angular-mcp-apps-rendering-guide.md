# Angular MCP Apps Rendering Guide

How MCP App HTML is loaded, rendered in an iframe, and communicates with the Angular host via the JSON-RPC postMessage protocol.

This document assumes you have read the [SSE Streaming Guide](./angular-sse-streaming-guide.md) and understand how interrupts work.

---

## Table of Contents

1. [What is an MCP App?](#what-is-an-mcp-app)
2. [Architecture Overview](#architecture-overview)
3. [The Two Communication Channels](#the-two-communication-channels)
4. [Trigger: The `mcp_app` Interrupt](#trigger-the-mcp_app-interrupt)
5. [McpService — The MCP Client](#mcpservice--the-mcp-client)
6. [McpPanelComponent — The Host Bridge](#mcppanelcomponent--the-host-bridge)
7. [Lifecycle Sequence Diagram](#lifecycle-sequence-diagram)
8. [JSON-RPC postMessage Protocol](#json-rpc-postmessage-protocol)
9. [Resume Payloads — How MCP Apps Close the Loop](#resume-payloads--how-mcp-apps-close-the-loop)
10. [Backend: MCP Servers and Registry](#backend-mcp-servers-and-registry)
11. [Backend: Graph Nodes That Trigger MCP Apps](#backend-graph-nodes-that-trigger-mcp-apps)
12. [BFF Proxy for MCP](#bff-proxy-for-mcp)
13. [Adding a New MCP App End-to-End](#adding-a-new-mcp-app-end-to-end)
14. [File Reference](#file-reference)

---

## What is an MCP App?

An MCP App is a self-contained HTML application (built with Vite as a single `mcp-app.html` file) that:

1. **Lives on an MCP server** — served as a resource via the `resources/read` JSON-RPC method.
2. **Renders in an iframe** — the Angular host fetches the HTML and sets it as `srcdoc` on an iframe.
3. **Communicates via postMessage** — the iframe and host exchange JSON-RPC 2.0 messages through `window.postMessage`.
4. **Receives data from MCP tools** — the host calls an MCP tool on the server and forwards the result into the iframe.
5. **Returns results to the graph** — when the user finishes (submits a form, selects products), the iframe sends a `ui/message` to the host, which calls `chatService.resumeWithData()` to unfreeze the LangGraph.

In this codebase, there are two MCP Apps:

| MCP App | What it does | MCP Endpoint | Tool |
|---------|-------------|-------------|------|
| **Search App** | Faceted product search with multi-select | `/mcp/search-app` | `search-data-products` |
| **Question Form** | Dynamic form with sections (Mandatory, DDF, etc.) | `/mcp/question-form` | `open-question-form` |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│  BROWSER                                                                │
│                                                                         │
│  ┌──────────────┐    ┌──────────────────────────────────────────────┐   │
│  │              │    │  MCP Panel (McpPanelComponent)               │   │
│  │  Chat UI     │    │                                              │   │
│  │              │    │  ┌─────────────────────────┐                 │   │
│  │  messages[]  │    │  │ iframe (srcdoc)         │                 │   │
│  │  input box   │    │  │                         │  postMessage    │   │
│  │              │◄───┤  │  MCP App HTML           │◄───────────────►│   │
│  │              │    │  │  (search / form UI)     │                 │   │
│  │              │    │  │                         │                 │   │
│  └──────┬───────┘    │  └─────────────────────────┘                 │   │
│         │            │         ▲                                    │   │
│         │ SSE        │         │ JSON-RPC over postMessage          │   │
│         │ /api/      │         │ (ui/initialize, ui/message,        │   │
│         │ chat/      │         │  ui/notifications/tool-result)     │   │
│         │ stream     │         ▼                                    │   │
│         │            │  ┌─────────────────────────┐                 │   │
│         │            │  │ MCP Client (McpService)  │                │   │
│         │            │  │ JSON-RPC over HTTP       │                │   │
│         │            │  └──────────┬──────────────┘                 │   │
│         │            └─────────────┼────────────────────────────────┘   │
│         │                          │                                    │
└─────────┼──────────────────────────┼────────────────────────────────────┘
          │ REST/SSE                 │ JSON-RPC/HTTP
          │ /api/chat/stream         │ /mcp/{app-name}
          ▼                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  EXPRESS BFF  (proxy layer — localhost:4200)                             │
│    /api/*   ──►  http://localhost:8000/api/v1/*                         │
│    /mcp/*   ──►  http://localhost:8000/mcp/*                            │
└─────────────────────────────────────────────────────────────────────────┘
          │                          │
          ▼                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FASTAPI BACKEND  (localhost:8000)                                      │
│                                                                         │
│  Chat Routes (/api/v1/chat/*)      MCP Servers (via registry.py)       │
│       │                             /mcp/search-app                     │
│       ▼                               └─ search-data-products tool     │
│  LangGraph graph                      └─ ui://search-app resource      │
│    └─ search_app node ──►              /mcp/question-form               │
│       interrupt({type:"mcp_app"})       └─ open-question-form tool     │
│    └─ fill_form node  ──►               └─ ui://question-form resource │
│       interrupt({type:"mcp_app"})                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key insight**: The graph **never** calls the MCP server directly. The graph node defines *which* MCP App to open and *what* tool to call via the interrupt payload. The **frontend** does the actual MCP communication.

---

## The Two Communication Channels

The system uses two independent HTTP paths:

```
                     Browser
                    /       \
                   /         \
          SSE / REST           JSON-RPC over HTTP
     /api/chat/stream          /mcp/{app-name}
          |                         |
     Graph control             UI content & tool data
     (send, resume)            (HTML, search results, form template)
          |                         |
          ▼                         ▼
     ChatService ──►           MCP Server ──►
     LangGraph graph           resources/read → HTML
                               tools/call → structured data
```

| Channel | Protocol | Purpose | When used |
|---------|----------|---------|-----------|
| Chat API (`/api/chat/stream`) | SSE over HTTP POST | Send messages, receive tokens, handle interrupts, resume | Before and after MCP App interaction |
| MCP (`/mcp/{app-name}`) | JSON-RPC 2.0 over HTTP POST | Fetch app HTML, call MCP tools | While the MCP App panel is open |

---

## Trigger: The `mcp_app` Interrupt

An MCP App session starts when the LangGraph backend emits an `interrupt` SSE event where `interrupt_value.type === "mcp_app"`. This arrives through the normal `chat/stream` SSE channel.

### SSE event

```
event: interrupt
data: {
  "type": "interrupt",
  "interrupt_value": {
    "type": "mcp_app",
    "resource_uri": "ui://search-app/mcp-app.html",
    "mcp_endpoint": "/mcp/search-app",
    "tool_name": "search-data-products",
    "tool_args": { "filters": { "domain": "all", "product_type": "all" } },
    "context": { "mode": "multi_select" }
  },
  "thread_id": "550e8400-..."
}
```

### Interrupt payload fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"mcp_app"` | Tells the frontend to open the MCP panel instead of rendering inline UI |
| `resource_uri` | `string` | The MCP resource URI. Used in a `resources/read` JSON-RPC call to fetch the app HTML |
| `mcp_endpoint` | `string` | The HTTP path where the MCP server is mounted (e.g., `/mcp/search-app`). The `McpService` sends JSON-RPC requests here |
| `tool_name` | `string` | Which MCP tool to call after the app initializes. The result is sent into the iframe |
| `tool_args` | `object` | Arguments for the tool call (filters, section name, etc.) |
| `context` | `object` | Additional data passed to the iframe (selected products, draft form values, product index) |

### How it differs from other interrupts

| `interrupt_value.type` | Rendered by | Where |
|------------------------|-------------|-------|
| `facet_selection` | `MessageComponent` | Inline in chat bubble |
| `product_selection` | `MessageComponent` | Inline in chat bubble |
| `cart_review` | `MessageComponent` | Inline in chat bubble |
| `confirmation` | `MessageComponent` | Inline in chat bubble |
| **`mcp_app`** | **`McpPanelComponent`** | **Side panel with iframe** |

---

## McpService — The MCP Client

The MCP client lives entirely in the Angular frontend. It sends JSON-RPC 2.0 requests over HTTP to the MCP server endpoints. It does **not** use postMessage — that's the iframe communication channel handled by `McpPanelComponent`.

`core/services/mcp.service.ts`:

```typescript
import { Injectable, signal } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

const MCP_HEADERS = new HttpHeaders({
  'Content-Type': 'application/json',
  Accept: 'application/json',
});

@Injectable({ providedIn: 'root' })
export class McpService {
  mcpHtml = signal<string | null>(null);
  loading = signal<boolean>(false);

  private activeEndpoint = '/mcp/question-form';

  constructor(private http: HttpClient) {}

  /**
   * Set the MCP server endpoint dynamically.
   * Called when the interrupt specifies which MCP App to open.
   */
  setEndpoint(endpoint: string): void {
    this.activeEndpoint = endpoint;
  }

  /**
   * Fetch the MCP App HTML by calling resources/read via JSON-RPC.
   *
   * The server returns the complete HTML as a text string in
   * result.contents[0].text. This HTML is then set as the
   * iframe's srcdoc.
   */
  async fetchAppHtml(resourceUri: string, endpoint?: string): Promise<string> {
    const url = endpoint || this.activeEndpoint;
    this.loading.set(true);
    try {
      const body = {
        jsonrpc: '2.0',
        id: 1,
        method: 'resources/read',
        params: { uri: resourceUri },
      };
      const resp: any = await firstValueFrom(
        this.http.post(url, body, { headers: MCP_HEADERS })
      );

      const contents = resp?.result?.contents;
      if (contents && contents.length > 0) {
        const html = contents[0].text || contents[0].content || '';
        this.mcpHtml.set(html);
        return html;
      }
      throw new Error('No content in MCP response');
    } finally {
      this.loading.set(false);
    }
  }

  /**
   * Call an MCP tool via JSON-RPC.
   *
   * Returns the tool's result object, which typically contains
   * structuredContent (products, facets, form templates, etc.).
   */
  async callTool(
    toolName: string,
    args: Record<string, unknown>,
    endpoint?: string
  ): Promise<any> {
    const url = endpoint || this.activeEndpoint;
    const body = {
      jsonrpc: '2.0',
      id: 2,
      method: 'tools/call',
      params: { name: toolName, arguments: args },
    };
    const resp: any = await firstValueFrom(
      this.http.post(url, body, { headers: MCP_HEADERS })
    );
    return resp?.result;
  }

  clear(): void {
    this.mcpHtml.set(null);
  }
}
```

### JSON-RPC request/response examples

**Fetching app HTML** (`resources/read`):

```
POST /mcp/search-app
→ { "jsonrpc": "2.0", "id": 1, "method": "resources/read",
    "params": { "uri": "ui://search-app/mcp-app.html" } }

← { "jsonrpc": "2.0", "id": 1, "result": {
      "contents": [{ "text": "<!DOCTYPE html>...", "mimeType": "text/html;profile=mcp-app" }]
   }}
```

**Calling a tool** (`tools/call`):

```
POST /mcp/search-app
→ { "jsonrpc": "2.0", "id": 2, "method": "tools/call",
    "params": { "name": "search-data-products",
                "arguments": { "filters": { "domain": "all" } } } }

← { "jsonrpc": "2.0", "id": 2, "result": {
      "content": [{ "type": "text", "text": "Search loaded with 10 products..." }],
      "structuredContent": {
        "products": [ { "id": "dp-001", "title": "Patient Demographics", ... }, ... ],
        "facets": { "domains": [...], "product_types": [...] },
        "appliedFilters": { "domain": "all", "product_type": "all" }
      }
   }}
```

---

## McpPanelComponent — The Host Bridge

This component does three things:

1. **Watches for `mcp_app` interrupts** and opens the side panel.
2. **Loads the MCP App HTML** into an iframe via `srcdoc`.
3. **Bridges postMessage** between the iframe and the MCP server.

`features/mcp-panel/mcp-panel.component.ts`:

```typescript
@Component({
  selector: 'app-mcp-panel',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="panel" [class.open]="isOpen()">
      <div class="panel-header">
        <h3>{{ panelTitle() }}</h3>
        <button class="close-btn" (click)="close()">✕</button>
      </div>
      <div class="panel-body">
        @if (mcpService.loading()) {
          <div class="loading">Loading...</div>
        } @else if (iframeHtml()) {
          <iframe
            #mcpFrame
            class="mcp-iframe"
            sandbox="allow-scripts allow-same-origin"
            [srcdoc]="iframeHtml()"
          ></iframe>
        }
      </div>
    </div>
  `,
})
export class McpPanelComponent implements OnDestroy {
  chatService = inject(ChatService);
  mcpService = inject(McpService);
  private sanitizer = inject(DomSanitizer);

  isOpen = signal(false);
  iframeHtml = signal<SafeHtml | null>(null);
  panelTitle = signal('MCP App');

  @ViewChild('mcpFrame') mcpFrame!: ElementRef<HTMLIFrameElement>;

  private messageHandler = this.onIframeMessage.bind(this);
  private pendingToolPayload: Record<string, unknown> | null = null;
  private appInitialized = false;
  private currentEndpoint = '/mcp/question-form';

  constructor() {
    // Listen for postMessage from iframes.
    window.addEventListener('message', this.messageHandler);

    // React to interrupt changes.
    effect(() => {
      const interrupt = this.chatService.currentInterrupt();
      if (interrupt?.interrupt) {
        const val = interrupt.interrupt.interrupt_value;
        if (val?.['type'] === 'mcp_app') {
          this.openMcpApp(val as Record<string, unknown>);
        } else {
          this.isOpen.set(false);
        }
      } else {
        this.isOpen.set(false);
        this.iframeHtml.set(null);
        this.mcpService.clear();
      }
    });
  }

  ngOnDestroy(): void {
    window.removeEventListener('message', this.messageHandler);
  }
  // ... (methods shown below)
}
```

### Key methods

#### `openMcpApp(payload)` — Load and display the app

```typescript
async openMcpApp(payload: Record<string, unknown>): Promise<void> {
  this.isOpen.set(true);
  this.appInitialized = false;
  this.pendingToolPayload = payload;

  // The interrupt payload tells us which MCP server to use.
  const endpoint = (payload['mcp_endpoint'] as string) || '/mcp/question-form';
  this.currentEndpoint = endpoint;
  this.mcpService.setEndpoint(endpoint);

  // 1. Fetch the app HTML from the MCP server.
  const resourceUri = payload['resource_uri'] as string;
  const html = await this.mcpService.fetchAppHtml(resourceUri, endpoint);

  // 2. Sanitize and set as iframe srcdoc.
  this.iframeHtml.set(this.sanitizer.bypassSecurityTrustHtml(html));

  // The iframe will load and send ui/notifications/initialized,
  // which triggers sendToolResultToApp().
}
```

#### `sendToolResultToApp()` — Push data into the iframe

Called when the iframe signals it's ready (via `ui/notifications/initialized`):

```typescript
private async sendToolResultToApp(): Promise<void> {
  if (!this.pendingToolPayload) return;

  const toolName =
    (this.pendingToolPayload['tool_name'] as string) || 'open-question-form';
  const toolArgs =
    (this.pendingToolPayload['tool_args'] as Record<string, unknown>) || {};

  // 1. Call the MCP tool on the server (HTTP JSON-RPC).
  const result = await this.mcpService.callTool(
    toolName, toolArgs, this.currentEndpoint
  );

  // 2. Forward the result into the iframe via postMessage.
  const iframe = await this.waitForIframe();
  iframe?.contentWindow?.postMessage(
    {
      jsonrpc: '2.0',
      method: 'ui/notifications/tool-result',
      params: result,
    },
    '*'
  );
}
```

#### `handleAppMessage(params)` — Receive the user's submission

When the iframe sends a `ui/message`, the host extracts the result and resumes the graph:

```typescript
private handleAppMessage(params: any): void {
  const text = params?.content?.[0]?.text || JSON.stringify(params);

  if (this.currentEndpoint.includes('search-app')) {
    // Search app sends { action: "select_products", selected_products: [...] }
    try {
      const parsed = JSON.parse(text);
      if (parsed.action === 'select_products') {
        this.chatService.resumeWithData({
          selected_products: parsed.selected_products,
        });
        this.close();
        return;
      }
    } catch {}
    this.chatService.resumeWithData({ cancelled: true });
    this.close();
  } else {
    // Question form sends the completed form data.
    this.chatService.resumeWithData({ form_data: text, submitted: true });
    this.close();
  }
}
```

---

## Lifecycle Sequence Diagram

```
   User        Chat UI        MCP Panel       McpService       BFF        MCP Server      LangGraph
    │              │               │               │             │             │              │
    │  types msg   │               │               │             │             │              │
    ├──────────────►               │               │             │             │              │
    │              │── POST /api/chat/stream ──────────────────►│─────────────►│              │
    │              │                               │             │             │     ainvoke() │
    │              │                               │             │             │       │       │
    │              │                               │             │             │   interrupt() │
    │              │                               │             │             │   type:mcp_app│
    │              │◄── SSE event: interrupt ──────────────────────────────────────────────────┤
    │              │                               │             │             │              │
    │              │  currentInterrupt.set(...)     │             │             │              │
    │              │──────────────►│               │             │             │              │
    │              │  effect() detects mcp_app     │             │             │              │
    │              │               │               │             │             │              │
    │              │               │──fetchAppHtml()──►          │             │              │
    │              │               │               │──POST /mcp/search-app───►│              │
    │              │               │               │  resources/read          │──────────────►│
    │              │               │               │◄─ { text: "<html>..." } ─┤              │
    │              │               │◄──────────────┤             │             │              │
    │              │               │ set iframe srcdoc           │             │              │
    │              │               │               │             │             │              │
    │              │               │◄── postMessage ──┐          │             │              │
    │              │               │  ui/initialize   │ iframe   │             │              │
    │              │               │── postMessage ──► │          │             │              │
    │              │               │  {hostInfo,...}   │          │             │              │
    │              │               │                   │          │             │              │
    │              │               │◄── postMessage ──┘          │             │              │
    │              │               │  ui/notifications/          │             │              │
    │              │               │  initialized                │             │              │
    │              │               │                              │             │              │
    │              │               │──callTool()────►             │             │              │
    │              │               │               │──POST /mcp/search-app───►│              │
    │              │               │               │  tools/call               │              │
    │              │               │               │◄─ structuredContent ──────┤              │
    │              │               │◄──────────────┤             │             │              │
    │              │               │── postMessage ──┐           │             │              │
    │              │               │  tool-result     │ iframe   │             │              │
    │              │               │                  ▼          │             │              │
    │              │               │   App renders search/form   │             │              │
    │              │               │                   │         │             │              │
    │  selects     │               │◄── postMessage ──┘         │             │              │
    │  products    │               │  ui/message                 │             │              │
    │              │               │  {select_products:[...]}    │             │              │
    │              │               │                              │             │              │
    │              │◄──────────────┤  resumeWithData(...)         │             │              │
    │              │── POST /api/chat/stream {action:"resume"} ─►│─────────────►│              │
    │              │                               │             │             │  Command     │
    │              │                               │             │             │  (resume=...)│
    │              │◄── SSE token/done/interrupt ──────────────────────────────────────────────┤
    │              │               │               │             │             │              │
```

---

## JSON-RPC postMessage Protocol

All communication between the iframe (MCP App) and the host (`McpPanelComponent`) uses JSON-RPC 2.0 over `window.postMessage`.

### Messages FROM iframe TO host

#### Requests (require a response)

The iframe sends a request; the host responds via `postMessage` back to the iframe.

| Method | When | Host response |
|--------|------|---------------|
| `ui/initialize` | Immediately after iframe loads | `{ protocolVersion, hostInfo, hostCapabilities, hostContext }` |
| `ui/update-model-context` | App wants to update context | `{}` |
| `ui/message` | User submits form / selects products | `{}` (host also calls `resumeWithData`) |
| `ui/open-link` | App wants to open a URL | `{ isError: false }` |
| `ui/request-display-mode` | App requests inline/overlay mode | `{ mode: "inline" }` |
| `ui/resource-teardown` | App is cleaning up | `{}` |
| `ping` | Health check | `{}` |
| `tools/call` | App wants to call an MCP tool directly | Tool result from server |

#### Notifications (no response expected)

| Method | When | Host action |
|--------|------|-------------|
| `ui/notifications/initialized` | After receiving `ui/initialize` response | Host calls the MCP tool and sends result via `tool-result` |
| `ui/notifications/size-changed` | App changed its size | (ignored) |
| `ui/notifications/request-teardown` | App wants to close | Host closes the panel |

### Messages FROM host TO iframe

| Method | When | Payload |
|--------|------|---------|
| `ui/notifications/tool-result` (notification) | After tool call completes | `{ structuredContent: { products, facets, ... } }` |
| Response to `ui/initialize` | After receiving initialize request | `{ protocolVersion, hostInfo, hostCapabilities, hostContext }` |
| Response to `tools/call` | After proxying tool call | Tool result from server |

### Request/Response format

```typescript
// Iframe → Host (request)
{
  jsonrpc: '2.0',
  id: 1,                              // numeric ID, required for requests
  method: 'ui/initialize',
  params: { protocolVersion: '2026-01-26' }
}

// Host → Iframe (response)
{
  jsonrpc: '2.0',
  id: 1,                              // same ID as the request
  result: {
    protocolVersion: '2026-01-26',
    hostInfo: { name: 'DataGovernanceChat', version: '1.0.0' },
    hostCapabilities: { updateModelContext: { text: {} }, message: { text: {} } },
    hostContext: { theme: 'light', displayMode: 'inline' }
  }
}

// Host → Iframe (notification — no id)
{
  jsonrpc: '2.0',
  method: 'ui/notifications/tool-result',
  params: { structuredContent: { products: [...], facets: {...} } }
}
```

### How the host identifies iframe messages

```typescript
private onIframeMessage(event: MessageEvent): void {
  const data = event.data;

  // 1. Only process JSON-RPC messages
  if (!data || typeof data !== 'object' || data.jsonrpc !== '2.0') return;

  // 2. Only process if panel is open
  if (!this.isOpen()) return;

  // 3. Verify the message came from our iframe
  const iframe = this.mcpFrame?.nativeElement;
  if (iframe && event.source === iframe.contentWindow) {
    if (data.method && data.id != null) {
      this.handleRequest(data, iframe);   // request (has id)
    } else if (data.method && data.id == null) {
      this.handleNotification(data);       // notification (no id)
    }
  }
}
```

---

## Resume Payloads — How MCP Apps Close the Loop

When the MCP App session ends, the host calls `chatService.resumeWithData(payload)` which POSTs to `/api/chat/stream` with `action: "resume"`. The `resume_data` is what the graph node's `interrupt()` call returns.

### Search App

| User action | Resume payload | What the graph node does |
|-------------|---------------|--------------------------|
| Selects products and confirms | `{ selected_products: [{id, title, ...}, ...] }` | Stores in `state.selected_products`, routes to `review_cart` |
| Cancels / closes panel | `{ cancelled: true }` | Treats as empty selection |
| Types in chat while panel open | `{ action: "user_message", text: "..." }` | Node responds that panel is still open |

### Question Form

| User action | Resume payload | What the graph node does |
|-------------|---------------|--------------------------|
| Submits form | `{ form_data: "{...json...}", submitted: true }` | Stores in `state.form_drafts[product_id]`, advances to next product |
| Clicks "Add More" | `{ action: "add_more" }` | Routes back to `narrow_search` to add more products |
| Types "go back to products" | `{ action: "user_message", text: "..." }` | LLM classifies intent → may route to `review_cart` or `narrow_search` |

### The full loop

```
interrupt({type:"mcp_app", ...})    ◄── Graph pauses
         │
         ▼
SSE interrupt event → frontend opens panel
         │
         ▼
User interacts with MCP App in iframe
         │
         ▼
iframe sends ui/message → handleAppMessage()
         │
         ▼
chatService.resumeWithData(payload)
         │
         ▼
POST /api/chat/stream {action:"resume", resume_data: payload}
         │
         ▼
Backend: Command(resume=payload)
         │
         ▼
interrupt() RETURNS payload        ◄── Graph resumes
         │
         ▼
Node processes payload, updates state, routes to next node
```

---

## Backend: MCP Servers and Registry

### How MCP servers are mounted

MCP servers are Python modules under `backend/app/mcp/`. Each has a `server.py` with a `create_server()` function that returns an MCP `Server` instance.

The `registry.py` auto-discovers them and mounts each as ASGI middleware at `/mcp/{name}`:

```python
MCP_APPS = [
    {"name": "question-form", "folder": "question-form-app-python"},
    {"name": "search-app",    "folder": "search-app"},
]
```

This means:
- `POST /mcp/question-form` → routes to the Question Form MCP server
- `POST /mcp/search-app` → routes to the Search App MCP server

### MCP server structure

Each MCP server defines:

1. **Tools** — callable functions with input schemas. Example: `search-data-products` takes `{filters: {domain, product_type}}` and returns `structuredContent` with products and facets.

2. **Resources** — the app HTML. Example: `ui://search-app/mcp-app.html` returns the built Vite HTML file from `dist/mcp-app.html`.

The `_meta.ui.resourceUri` field on each tool links the tool to its UI resource, telling the host which HTML to load when the tool is rendered.

### Building the MCP App HTML

Each MCP App has a Vite build that compiles TypeScript source into a single `mcp-app.html`:

```bash
cd backend/app/mcp/search-app
npm install && npm run build    # → dist/mcp-app.html

cd backend/app/mcp/question-form-app-python
npm install && npm run build    # → dist/mcp-app.html
```

---

## Backend: Graph Nodes That Trigger MCP Apps

### Search App node (`search_app_node`)

```python
def search_app_node(state: AccessRequestState) -> dict:
    result = interrupt({
        "type": "mcp_app",
        "resource_uri": "ui://search-app/mcp-app.html",
        "mcp_endpoint": "/mcp/search-app",
        "tool_name": "search-data-products",
        "tool_args": {
            "filters": { "domain": "all", "product_type": "all" },
        },
        "context": {"mode": "multi_select"},
    })

    # interrupt() returns whatever resumeWithData() sent
    products = result.get("selected_products", [])
    return {
        "selected_products": products,
        "current_step": "review_cart",
    }
```

### Fill Form node (`fill_form_node`)

```python
def fill_form_node(state: AccessRequestState) -> dict:
    product = state["selected_products"][state["current_product_index"]]
    section = _resolve_section(product)

    form_data = interrupt({
        "type": "mcp_app",
        "resource_uri": "ui://question-form/mcp-app.html",
        "mcp_endpoint": "/mcp/question-form",
        "tool_name": "open-question-form",
        "tool_args": {"section": section},
        "context": {
            "selected_product": product,
            "draft_values": existing_draft,
            "product_type": section,
            "product_index": idx,
            "total_products": len(products),
        },
    })

    # interrupt() returns the form submission
    form_drafts[product_id] = form_data
    return {
        "form_drafts": form_drafts,
        "current_product_index": idx + 1,
    }
```

---

## BFF Proxy for MCP

The Express BFF proxies MCP requests with a simple path rewrite:

```typescript
app.use(
  '/mcp',
  createProxyMiddleware({
    target: BACKEND_URL,
    changeOrigin: true,
    pathRewrite: (_path) => `/mcp${_path}`,
  })
);
```

| Browser request | Proxy target |
|----------------|-------------|
| `POST /mcp/search-app` | `POST http://localhost:8000/mcp/search-app` |
| `POST /mcp/question-form` | `POST http://localhost:8000/mcp/question-form` |

No special SSE handling needed here — MCP uses standard HTTP POST with JSON responses.

---

## Adding a New MCP App End-to-End

### 1. Create the MCP server

```
backend/app/mcp/my-new-app/
├── server.py          # create_server() → Server
├── src/
│   └── mcp-app.ts     # TypeScript UI source
├── package.json       # Vite build config
└── dist/
    └── mcp-app.html   # Built output (gitignored, built via npm run build)
```

`server.py`:
```python
from mcp.server.lowlevel import Server
import mcp.types as types

RESOURCE_URI = "ui://my-new-app/mcp-app.html"

def create_server() -> Server:
    server = Server("My New App")

    @server.list_tools()
    async def handle_list_tools():
        return [types.Tool.model_validate({
            "name": "my-tool",
            "description": "Does something cool",
            "inputSchema": { "type": "object", "properties": {...} },
            "_meta": { "ui": {"resourceUri": RESOURCE_URI} },
        })]

    @server.call_tool()
    async def handle_call_tool(name, arguments):
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="Loaded")],
            structuredContent={ "data": "..." },
        )

    @server.list_resources()
    async def handle_list_resources():
        return [types.Resource(
            uri=RESOURCE_URI,
            name="My App UI",
            mimeType="text/html;profile=mcp-app",
        )]

    @server.read_resource()
    async def handle_read_resource(uri):
        from mcp.server.lowlevel.server import ReadResourceContents
        html = (Path(__file__).parent / "dist/mcp-app.html").read_text()
        return [ReadResourceContents(content=html, mime_type="text/html;profile=mcp-app")]

    return server
```

### 2. Register in the registry

In `backend/app/mcp/registry.py`:

```python
MCP_APPS = [
    {"name": "question-form", "folder": "question-form-app-python"},
    {"name": "search-app",    "folder": "search-app"},
    {"name": "my-new-app",    "folder": "my-new-app"},  # ← add this
]
```

### 3. Create the graph node

```python
def my_new_app_node(state):
    result = interrupt({
        "type": "mcp_app",
        "resource_uri": "ui://my-new-app/mcp-app.html",
        "mcp_endpoint": "/mcp/my-new-app",
        "tool_name": "my-tool",
        "tool_args": {},
        "context": {},
    })
    # Process result...
    return {updated state}
```

### 4. Handle the result in McpPanelComponent

In `handleAppMessage`, add a branch for the new endpoint:

```typescript
private handleAppMessage(params: any): void {
  const text = params?.content?.[0]?.text || JSON.stringify(params);

  if (this.currentEndpoint.includes('my-new-app')) {
    const parsed = JSON.parse(text);
    this.chatService.resumeWithData(parsed);
    this.close();
    return;
  }
  // ... existing handlers
}
```

### 5. Build the UI and test

```bash
cd backend/app/mcp/my-new-app
npm install && npm run build
```

---

## File Reference

| File | Layer | Purpose |
|------|-------|---------|
| `frontend/client/src/app/core/services/mcp.service.ts` | Frontend | MCP client — JSON-RPC over HTTP (resources/read, tools/call) |
| `frontend/client/src/app/features/mcp-panel/mcp-panel.component.ts` | Frontend | Host bridge — iframe + postMessage + tool forwarding |
| `frontend/client/src/app/core/services/chat.service.ts` | Frontend | Manages interrupt state + `resumeWithData()` |
| `frontend/client/src/app/core/models/chat.model.ts` | Frontend | `InterruptPayload` and SSE event interfaces |
| `frontend/server/src/index.ts` | BFF | Proxies `/mcp/*` to backend |
| `backend/app/mcp/registry.py` | Backend | Discovers and mounts MCP servers as ASGI middleware |
| `backend/app/mcp/search-app/server.py` | Backend | Search MCP server (tool + resource) |
| `backend/app/mcp/question-form-app-python/server.py` | Backend | Question Form MCP server (tool + resource) |
| `backend/app/graph/subgraphs/request_access/nodes/search_app.py` | Backend | Graph node that triggers Search App interrupt |
| `backend/app/graph/subgraphs/request_access/nodes/fill_form.py` | Backend | Graph node that triggers Question Form interrupt |
