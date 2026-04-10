# Questions Re-Answered — A Graph Design Expert's Perspective

These are the same six questions from the original Perplexity session, answered fresh by someone who deeply understands the full problem space — every edge case, every user behavior, every architectural pressure point — but has not yet written a line of code. This is how I'd advise you before you start building.

---

## Q1: Which agentic pattern should I use?

> I have a chat interface for a data governance app. Based on inferred user intent it must route to one of 3 flows:
> 1. Request access to data product (search → select → fill form → submit)
> 2. Information Q&A on the request access process
> 3. Check status of existing request
>
> Considerations:
> a. What if the user in the middle of flow 1 asks a question intended for flow 2?
> b. What if the user in the middle of flow 1 wants to check status?

### Answer

Use a **supervisor-with-tools** pattern at the top level, and a **directed graph (not a chain) with conditional edges** for flow 1. Flows 2 and 3 are simple enough to be single nodes.

#### The supervisor

Bind LLM tools for each intent and use `Command` to route:

```python
def supervisor_node(state) -> Command[Literal["request_access", "faq", "status_check", "__end__"]]:
    response = llm_with_tools.invoke([SYSTEM_PROMPT] + state["messages"])
    if not response.tool_calls:
        return {"messages": [response]}   # clarifying question
    tc = response.tool_calls[0]
    return Command(update={"active_intent": tc["name"]}, goto=tc["name"])
```

Do not add static edges (`add_edge`) from the supervisor. `Command` handles all routing. If you mix the two, both targets execute — this is a silent, difficult-to-debug error.

#### Flow 1 is a directed graph, not a pipeline

Here is the critical insight most people miss: **the access request flow is not linear**. It looks linear on paper (search → select → form → submit), but real users:

- Search, get zero results, and need to broaden their filters
- Select products, start filling a form, then realize they picked the wrong product
- Fill half a form, want to add another product, then come back to finish the form
- Complete a form, see the summary, and want to edit a specific product's form

This means every step needs the ability to route **backward** as well as forward. Design the subgraph as a directed graph with conditional edges at every transition:

```
START → narrow → show_results ⟷ search_app (MCP)
                      ↓
                 review_cart ⟷ narrow (add more)
                      ↓
                  fill_form ⟷ review_cart (change selection)
                      ↕
                   confirm ⟷ fill_form (edit form)
                      ↓
                   submit → END
```

Every arrow marked ⟷ is a conditional edge. The routing function at each node checks a `current_step` field in state to decide where to go next:

```python
def _route_after_fill_form(state) -> str:
    step = state.get("current_step", "")
    if step == "fill_form":    return "fill_form"     # next product's form
    if step == "narrow":       return "narrow"         # add more products
    if step == "review_cart":  return "review_cart"    # back to selection
    return "confirm"                                   # done, go to summary
```

This pattern — where each node sets `current_step` and each routing function reads it — is the cleanest way to implement backtracking in LangGraph. Avoid encoding routing logic in complex conditionals spread across the graph builder; keep each routing function a simple switch on `current_step`.

#### The conversational funnel

Flow 1 should follow a **conversational funnel** pattern: start broad and narrow progressively. Don't dump the user into a search box immediately. Instead:

1. **Narrow by domain** — "What domain are you interested in?" (faceted selection)
2. **Narrow by type** — "What type of data product?" (faceted selection)
3. **Show filtered results** — present matches with ability to select or open advanced search
4. **Review cart** — confirm selections before moving to forms
5. **Fill forms** — one per product, with per-product drafts
6. **Confirm** — summary view before submission
7. **Submit** — final action

Each step is an `interrupt()`. Each step collects one thing and advances. This prevents overwhelming the user and gives you clean routing boundaries.

#### Considerations (a) and (b): mid-flow questions and status checks

When the user is mid-flow-1 and asks a question or requests a status check, you have two options:

**Option A: Handle it inside the subgraph node (recommended).** The graph is paused at an `interrupt()`. When the user types a free-text message, resume the interrupt with `{ action: "user_message", text: "..." }`. The node classifies the intent using a lightweight LLM call and either:
- Routes within the subgraph (e.g., back to search, add more products)
- Answers the question inline and keeps the form open
- Routes to a different step

**Option B: Handle it externally in the gateway.** Classify the message outside the graph and either run a separate agent (FAQ/status) without touching the paused graph, or resume the graph with a special action.

Option A is better because the node has the full state context (which product, which form, what drafts exist). External orchestration would need to pass all that context around, which is fragile.

However, there is a subtle limitation: if the user wants a genuine FAQ answer (not navigation), someone has to answer it. You can either:
- Add a `faq_question` intent to the node's classifier and have the node call the FAQ service directly
- Or accept a brief context switch where the form stays open and the chat shows an FAQ answer separately

Do **not** abandon the paused graph state. The user should always be able to resume where they left off.

---

## Q2: Do subgraphs share the same thread_id with checkpointer?

> Does subgraphs reside under the same thread_id when using checkpointer mechanism?

### Answer

Yes, always. The subgraph executes under the parent's `thread_id`. But the subgraph's checkpointer setting determines **how much state survives between invocations**.

| Setting | Interrupts work? | State persists between invoke() calls? | Use for |
|:--|:--|:--|:--|
| `checkpointer=False` | No | No | Stateless utility subgraphs |
| `checkpointer=None` (default) | Yes | No | Single-turn interrupt/resume |
| `checkpointer=True` | Yes | Yes | Multi-step flows with multiple interrupt/resume cycles |

For the access request flow, you **must** use `checkpointer=True`. The flow has 5+ interrupt/resume cycles (domain selection, type selection, product selection, form filling per product, confirmation). Without `checkpointer=True`, the subgraph loses its internal state after each resume and starts from scratch.

Compile like this:

```python
access_subgraph = build_request_access_subgraph().compile(checkpointer=True)
parent_graph = parent_builder.compile(checkpointer=PostgresSaver(...))
```

The parent's checkpointer does the actual storage. `checkpointer=True` on the subgraph tells LangGraph to use the parent's checkpointer for the subgraph's state.

#### Practical rules

1. Use `AsyncPostgresSaver` (not `InMemorySaver`) from day one. In-memory checkpointing loses all state on server restart, which makes testing painful and production impossible.
2. Call `checkpointer.setup()` once at startup to create the checkpoint tables.
3. Use `get_state(config, subgraphs=True)` for debugging — it shows the full subgraph state including which interrupt the flow is paused at.
4. Never run the same `checkpointer=True` subgraph instance in parallel within one node — they write to the same checkpoint namespace and will conflict.

---

## Q3: Can subgraphs communicate directly with the user?

> Can subgraphs communicate directly to user? I intend the search and form to be interactive via an MCP App.

### Answer

Yes, through `interrupt()`. But what you're really asking is: how do I trigger a rich interactive UI (an MCP App) from a graph node, have the user interact with it, and get structured data back?

The answer is a three-part pattern: **interrupt payload as contract**, **generic host runtime**, and **structured resume**.

#### Part 1: The interrupt payload is a self-describing contract

Every node that needs an MCP App emits an interrupt with everything the frontend needs to render it:

```python
form_data = interrupt({
    "type": "mcp_app",
    "resource_uri": "ui://question-form/mcp-app.html",
    "mcp_endpoint": "/mcp/question-form",
    "tool_name": "open-question-form",
    "tool_args": {"section": "clinical"},
    "context": {
        "selected_product": product,
        "draft_values": existing_draft,
        "product_index": 0,
        "total_products": 3,
    },
})
```

The payload tells the frontend:
- **What** to render (`type: "mcp_app"`)
- **Where** to get the HTML (`resource_uri`)
- **Where** to send tool calls (`mcp_endpoint`)
- **Which** tool to invoke on load (`tool_name`, `tool_args`)
- **What** context to pass to the app (`context`)

This is the critical design principle: **the frontend should be completely generic**. It reads the payload and dynamically loads whatever MCP App the backend asks for. Adding a new MCP App should require zero frontend changes — only a new backend node that emits the right interrupt, a new MCP server, and a registry entry.

#### Part 2: The host is a generic MCP App runtime

The frontend component that hosts MCP Apps should:
1. React to any interrupt with `type: "mcp_app"`
2. Fetch HTML from the `mcp_endpoint` using JSON-RPC `resources/read`
3. Load the HTML into a sandboxed iframe via `srcdoc`
4. Handle the MCP Apps protocol over `postMessage` (JSON-RPC 2.0)
5. Forward tool calls from the iframe to the MCP server
6. Resume the graph when the app sends a completion message

This component never needs to know about specific MCP Apps. It's a bridge between two protocols:

| Direction | Protocol | Transport |
|:--|:--|:--|
| Graph ↔ Frontend | REST + interrupt/resume | HTTP |
| Host ↔ Iframe | JSON-RPC 2.0 (MCP Apps SDK) | `postMessage` |

#### Part 3: Structured resume data

When the MCP App completes, the frontend resumes the graph with structured data:

```python
# Form submission
Command(resume={"purpose": "...", "justification": "...", "approver": "..."})

# Search selection
Command(resume={"selected_products": [{"id": "dp-008", ...}, ...]})

# Explicit actions (button clicks, not from the MCP App)
Command(resume={"action": "add_more"})
Command(resume={"action": "back_to_selection"})
```

The node processes the resume value after `interrupt()` returns. Put all side effects (saving data, logging) **after** the interrupt call — code before it re-executes on every resume.

#### Non-MCP interrupts

Not every interrupt needs an MCP App. Simple interactions like facet selection or confirmation can use plain interrupts that the frontend renders as buttons or simple forms:

```python
interrupt({
    "type": "facet_selection",
    "facet": "domain",
    "message": "What domain?",
    "options": [{"id": "clinical", "label": "Clinical"}, ...],
})
```

Use `type` to discriminate. The frontend reads `type` and renders the appropriate UI component.

#### A warning about iframe timing

When loading an MCP App into an iframe, there's a race condition: the iframe's `contentWindow` may not be available when Angular (or React) first renders the element. Use a polling/retry mechanism to wait for the iframe before sending `postMessage`:

```typescript
waitForIframe(retries = 20, delayMs = 50): Promise<HTMLIFrameElement | null> {
    return new Promise((resolve) => {
        const check = (attempt) => {
            const el = this.mcpFrame?.nativeElement;
            if (el?.contentWindow) resolve(el);
            else if (attempt < retries) setTimeout(() => check(attempt + 1), delayMs);
            else resolve(null);
        };
        check(0);
    });
}
```

Without this, the MCP App will appear to "stall" because the host sends tool results before the iframe is ready to receive them.

---

## Q4: What if the MCP app is invoked from a subgraph node?

> I mean, the MCP app is invoked from one of the nodes on the subgraph.

### Answer

This is the primary pattern — MCP Apps should always be invoked from subgraph nodes. The interrupt propagates upward through the parent graph to the API layer automatically.

#### The full chain

Here is every step, because understanding the full chain prevents a class of debugging headaches:

```
1.  fill_form_node calls interrupt({type: "mcp_app", ...})
2.  LangGraph pauses the subgraph
3.  Parent graph's invoke() returns with __interrupt__ in the response
4.  Your API endpoint extracts the interrupt value and returns it as JSON
5.  Frontend stores it in a reactive signal (e.g., currentInterrupt)
6.  A UI component detects type === "mcp_app" and opens the MCP panel
7.  Panel sends resources/read to mcp_endpoint → gets HTML
8.  Panel loads HTML into iframe via srcdoc
9.  Iframe boots MCP Apps SDK, sends ui/initialize via postMessage
10. Host responds with hostInfo, capabilities, context
11. Iframe sends ui/notifications/initialized
12. Host calls the tool (tool_name + tool_args) on the MCP server
13. Host sends ui/notifications/tool-result to iframe via postMessage
14. App renders with the data, user interacts
15. App sends ui/message with structured result
16. Host calls resumeWithData(result)
17. API sends Command(resume=result) to the graph
18. interrupt() returns the result in fill_form_node
19. Node processes result and returns new state
20. Graph routes to the next node based on current_step
```

Steps 9–15 are the MCP Apps protocol — JSON-RPC 2.0 over `postMessage`. Steps 1–8 and 16–20 are your application's interrupt/resume protocol over HTTP.

#### Mount MCP servers in-process

Don't run MCP servers as separate processes unless you have a specific scaling reason. Mount them as ASGI middleware on the same FastAPI app:

```python
MCP_APPS = [
    {"name": "question-form", "folder": "question-form-app-python"},
    {"name": "search-app",    "folder": "search-app"},
]

def mount_mcp_servers(app: FastAPI):
    for app_def in MCP_APPS:
        # Load server.py, create StreamableHTTPSessionManager
        # Mount at /mcp/{name} via ASGI middleware
```

Each MCP server's `server.py` defines:
- **Resources** — `resources/read` handler that returns the HTML (built as a single-file bundle via Vite)
- **Tools** — `tools/call` handlers for data operations (search, form template loading)

The registry discovers servers at startup, initializes their session managers, and mounts them on the FastAPI router. Path rewriting strips the `/mcp/{name}` prefix so each server thinks it's mounted at `/mcp` internally.

#### Do not hide the subgraph inside a tool

```python
# WRONG — state inspection breaks, checkpointing is unreliable
@tool
def request_access_tool(query: str):
    return access_request_subgraph.invoke({"query": query})
builder.add_node("tools", ToolNode([request_access_tool]))

# CORRECT — the subgraph is a first-class node
builder.add_node("request_access", access_request_subgraph)
```

When the subgraph is a named node, you get:
- State inspection with `get_state(config, subgraphs=True)`
- Proper interrupt propagation
- Clean checkpoint namespacing

---

## Q5: What if the user changes intent mid-MCP-interaction?

> What if in the middle of the interaction the user asks a question or intent switch?

### Answer

This is the hardest problem in the entire system, and the answer that most architects get wrong. Let me be direct about what works and what doesn't.

#### What does NOT work: frontend pattern matching

You will be tempted to intercept user messages on the frontend and classify intent using string matching:

```typescript
// DO NOT DO THIS
const patterns = ['go back', 'change selection', 'back to products', ...];
if (patterns.some(p => message.includes(p))) {
    resumeWith({ action: 'back_to_selection' });
}
```

This fails immediately. Users say "can you go back to data product search" and your patterns have "go back to select" and "back to products" — neither matches. Natural language has infinite surface forms for the same intent. You cannot enumerate them.

#### What DOES work: LLM classification at the interrupt boundary

When the user types free text while the graph is paused at an MCP App interrupt, the frontend should do one thing: pass the raw text to the backend.

**Frontend — dead simple:**
```typescript
if (interruptType === 'mcp_app') {
    resumeWith({ action: 'user_message', text: message });
    return;
}
```

**Backend — LLM classifies in context:**
```python
INTENT_PROMPT = """Classify the user's message into exactly ONE intent:
- back_to_selection: wants to go back to product selection
- add_more: wants to add more products
- continue: wants to keep filling the form or is asking something unrelated
Respond with ONLY the intent name."""

def _classify_form_intent(user_text: str) -> str:
    resp = classifier_llm.invoke([SystemMessage(content=INTENT_PROMPT),
                                   HumanMessage(content=user_text)])
    intent = resp.content.strip().lower()
    return intent if intent in ("back_to_selection", "add_more") else "continue"
```

Use a fast, cheap model for classification (`gpt-4o-mini` or equivalent). The classification is a simple prompt — it doesn't need a large model. At ~200ms latency and negligible cost, it's a better investment than maintaining a pattern list.

#### The two input channels

During an interrupt, the system receives input through two channels:

1. **Explicit UI actions** (button clicks, form submissions from the MCP App) — these arrive as structured data: `{ action: "add_more" }`, `{ form_data: {...} }`, `{ selected_products: [...] }`. No classification needed.

2. **Free-text chat messages** — these arrive as raw text. The user could be navigating ("go back to search"), asking a question ("what does this field mean?"), or expressing intent in any phrasing. These need LLM classification.

Both resume the same interrupt. The node handles both with a simple action check:

```python
action = form_data.get("action", "")

if action == "add_more":          # explicit button
    return route_to_narrow()
if action == "back_to_selection":  # explicit button
    return route_to_review_cart()
if action == "user_message":      # free text → classify
    classified = _classify_form_intent(form_data["text"])
    if classified == "back_to_selection":
        return route_to_review_cart()
    if classified == "add_more":
        return route_to_narrow()
    return keep_form_open_with_nudge()
# default: treat as form submission
save_form_data(form_data)
```

#### Why classification belongs in the node, not the gateway

The node has the richest context:
- Which product the user is filling the form for
- What drafts have been completed
- How many products remain
- The full conversation history

An external gateway classifier would need all this context passed to it, which is fragile and duplicative. The node already has it in `state`.

#### What about genuine cross-flow switches?

If the user asks "what is the data steward approval process?" while filling a form, that's a genuine FAQ question, not navigation. You have three options:

1. **Answer inline.** Add a `faq_question` intent to the classifier. When matched, the node calls the FAQ retrieval service directly and returns the answer while keeping `current_step = "fill_form"` so the form stays open.

2. **Let it fall through.** The classifier returns `continue`, and the response says "The form is still open. Please complete it, or let me know if you'd like to change your selection." The user can then ask the question after closing the form.

3. **Handle externally.** The frontend detects the FAQ-like nature of the question and runs a separate FAQ query without touching the paused graph. The graph remains paused, the answer appears in the chat, and the form stays open.

Option 1 is the most seamless user experience. Option 3 is the most architecturally clean. Option 2 is the pragmatic default.

---

## Q6: How should memory be managed for this pattern?

> What about memory management for this pattern?

### Answer

Three layers, but the details matter more than the structure.

#### Layer 1: Workflow state (checkpointed, thread-scoped)

This is the state that drives the graph. Design it with explicit fields for every piece of data that affects routing or rendering:

```python
class AccessRequestState(TypedDict):
    messages: Annotated[list, operator.add]
    current_step: str

    # Facet narrowing
    selected_domain: str
    selected_type: str

    # Search
    search_query: str
    search_results: list

    # Cart (multi-product)
    selected_products: list
    current_product_index: int

    # Forms (keyed by product id)
    form_drafts: dict
```

Key design decisions:

**`selected_products` must be a list, not a single item.** Even if v1 only supports one product, design for multi-select from the start. Adding multi-product support after the fact requires changing every node.

**`form_drafts` must be a dict keyed by product ID.** This is the most important state design decision. It enables:
- Draft preservation when the user navigates away and comes back
- Per-product form state (each product can have a different form template)
- Cross-product data sharing (e.g., a "purpose" field filled on the cart can be injected into every product's draft before the form renders)
- Partial completion (3 of 5 forms done, user adds another product, comes back to fill the remaining forms)

```python
form_drafts = {
    "dp-008": {"purpose": "Oncology trial analysis", "justification": "..."},
    "dp-010": {"purpose": "Oncology trial analysis"},  # pre-filled from cart
    "dp-012": {},  # not started yet
}
```

**`current_product_index` tracks form progress.** When the user fills forms for multiple products, this counter drives which product's form to show next. Combined with `form_drafts`, it enables resuming form-filling at exactly the right product.

**`current_step` is the universal routing signal.** Every node sets it. Every routing function reads it. This is the single source of truth for "where should the graph go next?"

#### Draft preservation across navigation

This is a pattern you must get right from the start. Whenever a node exits to a different step (adding more products, going back to selection, etc.), it must **preserve existing drafts**:

```python
if action == "back_to_selection":
    return {
        "form_drafts": form_drafts,  # preserve what's been filled
        "current_step": "review_cart",
    }
```

When the user returns to the form later, pass the drafts into the interrupt context:

```python
draft = form_drafts.get(product_id, {})
form_data = interrupt({
    "context": {
        "draft_values": draft,  # pre-fills the form
        ...
    },
})
```

This creates a seamless experience: the user navigates away, adds a product, comes back, and their partially filled form is exactly as they left it.

#### Cross-step data flow

Data from one step can pre-fill fields in a later step. For example, if the cart review collects a "purpose" text, that purpose can be injected into every product's draft before the form renders:

```python
purpose = state.get("request_purpose", "")
if purpose and "purpose" not in draft:
    draft["purpose"] = purpose
```

This works because the graph state is the single source of truth. Any node can read any state field and use it to enrich the interrupt payload.

#### Layer 2: Messages — keep them lean

The `messages` list with `Annotated[list, operator.add]` is for conversation history. Rules:

**Put in messages:**
- User natural-language turns
- Assistant response strings
- Compact summaries of workflow actions

**Keep out of messages:**
- Full product objects (put in `selected_products`)
- Form payloads (put in `form_drafts`)
- Search result lists (put in `search_results`)
- MCP App event payloads
- Large API responses

If you put large objects in messages, the LLM context window fills up fast and the supervisor's intent classification degrades because it's drowning in irrelevant data.

#### Layer 3: Long-term store (cross-thread)

For facts that should survive across conversations. Use LangGraph's `Store` (backed by PostgreSQL in production):

**Good candidates:**
- User's department or business unit (pre-fill domain facet)
- Preferred approver
- Common justification templates
- Products the user has accessed before (pre-rank search results)
- UX preferences

**Bad candidates (keep in thread state):**
- Current form draft
- Current step
- Active search results
- Paused flow state

You may not need the Store in v1. Thread-scoped checkpointing is sufficient for single-session flows. Add the Store when you have a clear cross-session use case.

#### Production checkpointing

Use `AsyncPostgresSaver` from day one:

```python
checkpointer = AsyncPostgresSaver.from_conn_string(DATABASE_URL)
await checkpointer.setup()  # creates tables, idempotent
graph = builder.compile(checkpointer=checkpointer)
```

`InMemorySaver` is tempting for development, but it loses all state on server restart. You'll waste time re-creating test conversations. PostgreSQL is fast enough for development and required for production — just use it everywhere.

---

## Appendix: Patterns You'll Discover

These are patterns that don't fit neatly into any single question but will emerge naturally as you build. Plan for them.

### Pattern 1: The interrupt payload is your API

The interrupt value is the contract between the backend graph and the frontend UI. Make it self-describing:

```python
interrupt({
    "type": "...",           # what kind of UI to render
    "resource_uri": "...",   # where to get the app HTML (for MCP Apps)
    "mcp_endpoint": "...",   # where to send JSON-RPC (for MCP Apps)
    "tool_name": "...",      # which tool to call on load
    "tool_args": {...},      # tool arguments
    "context": {...},        # rendering context
    "message": "...",        # human-readable text for the chat
    "options": [...],        # for simple selection UIs
    "actions": [...],        # for action buttons
})
```

The `type` field is the discriminator. The frontend reads `type` and renders the appropriate component. This means adding a new interaction mode (new MCP App, new button layout, new form type) is a backend-only change.

### Pattern 2: Two protocols, one bridge

Your frontend bridges two independent protocols:

| Protocol | Layer | Transport | Concern |
|:--|:--|:--|:--|
| REST interrupt/resume | Application | HTTP | Graph lifecycle |
| JSON-RPC 2.0 (MCP Apps) | UI | `postMessage` | Iframe communication |

The graph knows nothing about iframes. The iframe knows nothing about LangGraph. The host component is the adapter. Keep these layers cleanly separated — if you let graph concerns leak into the iframe protocol or vice versa, debugging becomes extremely difficult.

### Pattern 3: MCP servers as in-process middleware

Mount MCP servers on the same FastAPI app as ASGI middleware. Use a registry pattern that auto-discovers server folders:

```python
MCP_APPS = [
    {"name": "question-form", "folder": "question-form-app-python"},
    {"name": "search-app",    "folder": "search-app"},
]
```

Each server gets a `StreamableHTTPSessionManager` and is served at `/mcp/{name}`. Path rewriting makes each server think it's at `/mcp`. This avoids multi-process coordination, separate ports, and CORS complexity.

### Pattern 4: Build MCP App HTML as single-file bundles

Use Vite with `vite-plugin-singlefile` to bundle each MCP App's HTML, CSS, and JS into a single `.html` file. The MCP server's `resources/read` handler returns this file as text. The host loads it via `srcdoc`. This eliminates asset loading issues inside sandboxed iframes and makes the app self-contained.

### Pattern 5: Plan for the zero-results edge case

When the conversational funnel narrows to zero results (user picks a domain/type combination with no matching products), the UI must not dead-end. Always provide escape hatches:

- "Refine Filters" button to go back to the funnel
- "Open Search Panel" button to try the MCP App with broader filters
- Ensure these buttons are visible **even when the product list is empty**

If you only show buttons when `products.length > 0`, the zero-results case traps the user with no way to continue.

### Pattern 6: Buttons for certainty, LLM for ambiguity

Design your UI with two input channels:
- **Buttons and structured actions** for deterministic, unambiguous intents (select product, submit form, add more)
- **Free-text chat** for everything else, classified by an LLM on the backend

Never try to turn free text into structured actions using regex or keyword matching. It fails on the first unusual phrasing. The LLM classification adds ~200ms and costs fractions of a cent — it's always worth it.

### Pattern 7: Preserve state on every exit path

Every node that can exit to a different step must preserve accumulated state. The most common bug is a node that routes to "add more products" but forgets to carry `form_drafts` forward. Use a checklist:

- [ ] Does this exit path preserve `form_drafts`?
- [ ] Does this exit path preserve `selected_products`?
- [ ] Does this exit path reset only what needs resetting (e.g., `search_results`, `selected_domain`)?
- [ ] Does this exit path set `current_step` correctly?

If a node has 4 exit paths, write explicit return statements for all 4. Don't rely on a default return to handle edge cases — make every path explicit.
