# Plan v2 — Conversational Search + Multi-Product Cart + Search MCP App

## Design Philosophy

**Conversational funnel + MCP App escalation.** The chat handles simple, guided interactions (choosing from facet buttons). MCP Apps handle complex, interactive work (free-form search, form filling). This keeps the flow feeling natural rather than wizard-like.

**Skills used:** `create-mcp-app`, `add-app-to-server`, `build-mcp-app` (for the Search MCP App design), `mcp-builder` (for tool design).

---

## Architecture Changes

### Current Flow (v1)
```
supervisor → search_node (vector search → interrupt with product cards)
           → fill_form_node (interrupt with MCP App form)
           → confirm_node (interrupt with Yes/No)
           → submit_node
```

### New Flow (v2)
```
supervisor → narrow_node (interrupt: domain chips)
           → narrow_node (interrupt: type chips)      ← loops until facets chosen
           → show_results_node (interrupt: product cards + "Open Search" button)
           │
           ├─ [user clicks product] → select_node → fill_form_node → ...
           │
           └─ [user clicks "Open Search"] → search_app_node (interrupt: Search MCP App)
              └─ returns selected products list → review_cart_node
                 → fill_form_node (loops per product)
                 → confirm_node
                 → submit_node → [ask "Add another?"] → loops back to narrow_node
```

---

## 1. New MCP App: `search-app` (Data Product Search)

**Location:** `backend/app/mcp/search-app/`

### Structure (mirrors question-form-app-python)
```
backend/app/mcp/search-app/
├── server.py              # Python MCP server (low-level API)
├── src/
│   ├── mcp-app.ts         # Vanilla TS client-side app
│   └── global.css         # Styles
├── dist/
│   └── mcp-app.html       # Built single-file HTML (vite-plugin-singlefile)
├── mcp-app.html           # Vite entry point
├── vite.config.ts
├── tsconfig.json
├── package.json
└── package-lock.json
```

### Tool: `search-data-products`

```python
# Tool name: "search-data-products"
# Input: { query?: str, filters?: { domain?: str, product_type?: str, sensitivity?: str } }
# Output: { content: [text summary], structuredContent: { products: [...], facets: {...} } }
```

The tool:
- Accepts optional `query` (free text) and `filters` (domain, type, sensitivity)
- Calls `SearchService.search()` with filters applied
- Returns all 15 products if no query, or filtered results
- Returns `structuredContent` with products array and available facet values

### Resource: `ui://search-app/mcp-app.html`

The HTML app renders:
- **Search box** at top (debounced, calls `app.callServerTool("search-data-products", ...)`)
- **Facet filter chips/dropdowns** (Domain, Type, Sensitivity) — filter locally or re-query
- **Results list** with checkboxes for multi-select
- **Selection count badge** + **"Continue with N selected →"** button
- On "Continue" → `app.sendMessage()` with `{ type: "search_complete", selected_products: [...] }`

### Server-side (server.py)
- Python low-level MCP server (same pattern as question-form)
- Registers `search-data-products` tool with `_meta.ui.resourceUri`
- Registers resource serving `dist/mcp-app.html`
- Communicates with `SearchService` (import from `app.service.search_service`)
- Also provides an **app-only** tool `filter-data-products` that the UI can call for real-time filtering

---

## 2. State Schema Changes

### `AccessRequestState` (updated)

```python
class AccessRequestState(TypedDict):
    messages: Annotated[list, operator.add]
    current_step: str
    # Narrowing
    selected_domain: str         # NEW - e.g. "r_and_d", "all"
    selected_type: str           # NEW - e.g. "ddf", "all"
    # Search
    search_query: str
    search_results: list
    # Cart (multi-product)
    selected_products: list      # CHANGED from selected_product (singular)
    current_product_index: int   # NEW - which product we're filling form for
    # Forms
    form_drafts: dict            # CHANGED from form_draft - keyed by product_id
    form_template: dict | None
```

### Remove
- `selected_product: dict | None` → replaced by `selected_products: list`
- `form_draft: dict | None` → replaced by `form_drafts: dict`

---

## 3. Subgraph Node Changes

### 3a. NEW: `narrow_node` (replaces the immediate search)

**File:** `backend/app/graph/subgraphs/request_access/nodes/narrow.py`

Sends two sequential interrupts with facet options:

**Interrupt 1 — Domain:**
```python
interrupt({
    "type": "facet_selection",
    "facet": "domain",
    "message": "What domain are you interested in?",
    "options": [
        {"id": "r_and_d", "label": "R&D / Clinical"},
        {"id": "commercial", "label": "Commercial"},
        {"id": "safety", "label": "Safety"},
        {"id": "operations", "label": "Operations"},
        {"id": "all", "label": "All Domains"},
    ]
})
```

**Interrupt 2 — Type:**
```python
interrupt({
    "type": "facet_selection",
    "facet": "product_type",
    "message": "What type of data product?",
    "options": [
        {"id": "ddf", "label": "DDF"},
        {"id": "default", "label": "Default"},
        {"id": "onyx", "label": "Onyx"},
        {"id": "all", "label": "Any Type"},
    ]
})
```

Returns: `{ selected_domain, selected_type }`

### 3b. MODIFIED: `search_node` → `show_results_node`

**File:** `backend/app/graph/subgraphs/request_access/nodes/show_results.py`

- Uses `selected_domain` and `selected_type` from state to filter search
- Adds a `SearchService.search_with_filters(query, domain, product_type, k)` method
- Interrupt payload now includes an `"open_search"` action option:

```python
interrupt({
    "type": "product_selection",
    "message": "Here are the matching products...",
    "products": results,
    "allow_search": True,  # UI shows "Open Search" button
    "allow_multi_select": True,  # UI shows checkboxes
})
```

- If user selects a product directly → `{ action: "select", products: [product] }`
- If user clicks "Open Search" → `{ action: "open_search" }`

### 3c. NEW: `search_app_node` (Search MCP App)

**File:** `backend/app/graph/subgraphs/request_access/nodes/search_app.py`

Triggers the Search MCP App via interrupt:

```python
interrupt({
    "type": "mcp_app",
    "resource_uri": "ui://search-app/mcp-app.html",
    "mcp_endpoint": "/mcp/search-app",
    "tool_name": "search-data-products",
    "tool_args": {
        "filters": {
            "domain": state.get("selected_domain", "all"),
            "product_type": state.get("selected_type", "all"),
        }
    },
    "context": { "mode": "multi_select" }
})
```

Returns selected products list from the MCP App.

### 3d. NEW: `review_cart_node`

**File:** `backend/app/graph/subgraphs/request_access/nodes/review_cart.py`

Shows the cart summary and offers options:

```python
interrupt({
    "type": "cart_review",
    "message": "You've selected N data products: ...",
    "products": selected_products,
    "actions": ["fill_forms", "add_more", "change_selection"]
})
```

### 3e. MODIFIED: `fill_form_node`

- Now reads `selected_products[current_product_index]` instead of `selected_product`
- Stores result in `form_drafts[product_id]` instead of `form_draft`
- After form submission, increments `current_product_index`
- If more products remain → loops back to itself
- If all done → goes to confirm

### 3f. MODIFIED: `confirm_node`

- Shows summary for ALL products and their forms
- Adds "Add Another" action alongside Yes/No
- If "Add Another" → routes back to `narrow_node`

### 3g. MODIFIED: `submit_node`

- Submits all products as a single request
- Generates one request ID covering all products

---

## 4. Updated Subgraph Wiring

```python
def build_request_access_subgraph() -> StateGraph:
    builder = StateGraph(AccessRequestState)

    builder.add_node("narrow", narrow_node)
    builder.add_node("show_results", show_results_node)
    builder.add_node("search_app", search_app_node)
    builder.add_node("review_cart", review_cart_node)
    builder.add_node("fill_form", fill_form_node)
    builder.add_node("confirm", confirm_node)
    builder.add_node("submit", submit_node)

    # Flow
    builder.add_edge(START, "narrow")
    builder.add_edge("narrow", "show_results")
    builder.add_conditional_edges("show_results", route_after_results,
        ["fill_form", "search_app"])
    builder.add_edge("search_app", "review_cart")
    builder.add_conditional_edges("review_cart", route_after_cart,
        ["fill_form", "narrow"])
    builder.add_conditional_edges("fill_form", route_after_form,
        ["fill_form", "confirm"])  # loops for multi-product
    builder.add_conditional_edges("confirm", route_after_confirm,
        ["submit", "fill_form", "narrow"])  # narrow = "add another"
    builder.add_edge("submit", END)

    return builder
```

---

## 5. SearchService Enhancements

**File:** `backend/app/service/search_service.py`

Add filtered search method:

```python
def search_with_filters(
    self,
    query: str = "",
    domain: str = "all",
    product_type: str = "all",
    sensitivity: str = "all",
    k: int = 10,
) -> list[dict]:
    """Search with optional metadata filters."""
    where_filters = {}
    if domain != "all":
        where_filters["domain"] = domain
    if product_type != "all":
        where_filters["product_type"] = product_type
    if sensitivity != "all":
        where_filters["sensitivity"] = sensitivity

    where = where_filters if where_filters else None
    # ChromaDB supports metadata filtering via `where` parameter
    ...

def get_facets(self) -> dict:
    """Return available facet values from the corpus."""
    return {
        "domains": sorted(set(dp["metadata"]["domain"] for dp in DATA_PRODUCTS)),
        "product_types": sorted(set(dp["metadata"]["product_type"] for dp in DATA_PRODUCTS)),
        "sensitivities": sorted(set(dp["metadata"]["sensitivity"] for dp in DATA_PRODUCTS)),
    }
```

---

## 6. Angular UI Changes

### 6a. `message.component.ts` — New interrupt renderers

Add rendering for:
- **`facet_selection`** interrupts → render as clickable chips/buttons
- **`product_selection` with `allow_multi_select`** → checkboxes on product cards + "Open Search" button
- **`cart_review`** interrupts → product list with action buttons

### 6b. `chat.component.ts` — Handle new events

Add handlers:
- `onFacetSelected(facet, value)` → calls `resumeWithData`
- `onMultiProductSelected(products)` → calls `resumeWithData`
- `onOpenSearch()` → calls `resumeWithData({ action: "open_search" })`
- `onCartAction(action)` → calls `resumeWithData({ action })`

### 6c. `mcp-panel.component.ts` — Handle Search MCP App

Already handles `mcp_app` interrupts. The Search MCP App will follow the same pattern:
- Panel opens with Search App HTML
- User searches, selects products, clicks "Continue"
- App sends `sendMessage()` → panel catches it → calls `resumeWithData()`

### 6d. `mcp.service.ts` — Support multiple MCP endpoints

The service already points to a single `mcpBaseUrl`. Need to make the URL dynamic based on the `mcp_endpoint` in the interrupt payload.

---

## 7. MCP Registry Changes

**File:** `backend/app/mcp/registry.py`

- Import and instantiate `search-app` server alongside `question-form`
- Create a second `StreamableHTTPSessionManager` for the search app
- Mount at `/mcp/search-app`
- Update the middleware to match both `/mcp/question-form` and `/mcp/search-app`

---

## 8. Execution Order

| # | Task | Files Changed / Created |
|---|------|------------------------|
| 1 | Update `AccessRequestState` | `backend/app/graph/state.py` |
| 2 | Add `SearchService.search_with_filters()` and `get_facets()` | `backend/app/service/search_service.py` |
| 3 | Create `narrow_node` | `backend/app/graph/subgraphs/request_access/nodes/narrow.py` (NEW) |
| 4 | Refactor `search_node` → `show_results_node` | `nodes/search.py` → `nodes/show_results.py` (RENAME + MODIFY) |
| 5 | Create `search_app_node` | `nodes/search_app.py` (NEW) |
| 6 | Create `review_cart_node` | `nodes/review_cart.py` (NEW) |
| 7 | Modify `fill_form_node` for multi-product | `nodes/fill_form.py` (MODIFY) |
| 8 | Modify `confirm_node` for multi-product + "Add Another" | `nodes/confirm.py` (MODIFY) |
| 9 | Modify `submit_node` for multi-product | `nodes/submit.py` (MODIFY) |
| 10 | Rewire subgraph | `subgraphs/request_access/graph.py` (MODIFY) |
| 11 | Create Search MCP App server | `backend/app/mcp/search-app/server.py` (NEW) |
| 12 | Create Search MCP App client | `backend/app/mcp/search-app/src/mcp-app.ts` (NEW) |
| 13 | Create Search MCP App styles | `backend/app/mcp/search-app/src/global.css` (NEW) |
| 14 | Search MCP App build config | `backend/app/mcp/search-app/{vite.config.ts, tsconfig.json, package.json, mcp-app.html}` (NEW) |
| 15 | Build Search MCP App | `npm install && npm run build` in search-app/ |
| 16 | Update MCP registry | `backend/app/mcp/registry.py` (MODIFY) |
| 17 | Update Angular message component | `frontend/client/.../message/message.component.ts` (MODIFY) |
| 18 | Update Angular chat component | `frontend/client/.../chat/chat.component.ts` (MODIFY) |
| 19 | Update Angular MCP service | `frontend/client/.../mcp.service.ts` (MODIFY) |
| 20 | Update Angular MCP panel | `frontend/client/.../mcp-panel/mcp-panel.component.ts` (MODIFY) |
| 21 | Rebuild Angular + restart servers | Build + test |

---

## 9. Files Inventory

### New Files (8)
- `backend/app/graph/subgraphs/request_access/nodes/narrow.py`
- `backend/app/graph/subgraphs/request_access/nodes/show_results.py`
- `backend/app/graph/subgraphs/request_access/nodes/search_app.py`
- `backend/app/graph/subgraphs/request_access/nodes/review_cart.py`
- `backend/app/mcp/search-app/server.py`
- `backend/app/mcp/search-app/src/mcp-app.ts`
- `backend/app/mcp/search-app/src/global.css`
- `backend/app/mcp/search-app/{vite.config.ts, tsconfig.json, package.json, mcp-app.html}`

### Modified Files (11)
- `backend/app/graph/state.py`
- `backend/app/service/search_service.py`
- `backend/app/graph/subgraphs/request_access/nodes/fill_form.py`
- `backend/app/graph/subgraphs/request_access/nodes/confirm.py`
- `backend/app/graph/subgraphs/request_access/nodes/submit.py`
- `backend/app/graph/subgraphs/request_access/graph.py`
- `backend/app/mcp/registry.py`
- `frontend/client/src/app/features/chat/message/message.component.ts`
- `frontend/client/src/app/features/chat/chat.component.ts`
- `frontend/client/src/app/core/services/mcp.service.ts`
- `frontend/client/src/app/features/mcp-panel/mcp-panel.component.ts`

### Deleted Files (1)
- `backend/app/graph/subgraphs/request_access/nodes/search.py` (replaced by `show_results.py`)
