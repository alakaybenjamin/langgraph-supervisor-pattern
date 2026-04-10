# Questions Revisited — Lessons from Building the System

Answers to each original question, revisited now that we've built, tested, and iterated on the full architecture. These answers reflect what actually worked, what surprised us, and what we'd do differently.

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

### Revisited Answer

We used a **supervisor node with `Command`-based routing** and a **multi-node subgraph with conditional edges** for the access request flow. This worked well, but the real system is more nuanced than the original answer suggested.

#### What we actually built

The supervisor uses `ChatOpenAI` with bound tools to classify intent:

```python
_llm = ChatOpenAI(model="gpt-4o").bind_tools(SUPERVISOR_TOOLS)

def supervisor_node(state: SupervisorState) -> Command[...] | dict:
    messages = [SYSTEM_PROMPT] + state["messages"]
    response = _llm.invoke(messages)

    if not response.tool_calls:
        return {"messages": [response]}  # Clarifying question

    tc = response.tool_calls[0]
    if tc["name"] == "start_access_request":
        return Command(update={...}, goto="request_access")
    elif tc["name"] == "answer_question":
        return Command(update={...}, goto="faq")
    elif tc["name"] == "check_request_status":
        return Command(update={...}, goto="status_check")
```

The request_access subgraph is **not** a simple linear chain. It's a directed graph with conditional edges that allow the user to move backward and forward between steps:

```
narrow → show_results → review_cart → fill_form → confirm → submit
  ↑           ↑    ↓         ↑    ↓        ↑    ↓       ↓
  └───────────┘    └── search_app  └────────┘    └───────┘
                         (MCP App)                (back to cart)
```

Every transition is governed by a routing function that checks `current_step` in state:

```python
def _route_after_fill_form(state: AccessRequestState) -> str:
    step = state.get("current_step", "")
    if step == "fill_form":    return "fill_form"     # next product
    if step == "narrow":       return "narrow"         # add more products
    if step == "review_cart":  return "review_cart"    # back to selection
    return "confirm"
```

#### What the original answer got right

- Supervisor + `Command` routing is the correct pattern.
- `Command` must not coexist with `add_edge()` from the same node.
- The access request flow needs its own subgraph with explicit state management.

#### What the original answer underestimated

1. **The subgraph is a graph, not a chain.** The original answer showed `search → fill_form → confirm → submit`. The real system has 7 nodes with conditional edges forming a directed graph. Users backtrack, skip steps, and re-enter the flow at different points. Every node needs a routing function, not just a simple `add_edge()`.

2. **Conditional edges are the backbone.** Almost every edge in the subgraph is conditional. The only fixed edges are `START → narrow` and `submit → END`. Everything else uses `add_conditional_edges()` because the user's action determines the next step.

3. **The "conversational funnel" pattern matters.** The flow starts broad (which domain? which type?) and narrows progressively. This isn't just UX — it determines the graph topology. Each narrowing step is an interrupt that collects one piece of information and routes forward or backward.

#### Considerations (a) and (b): mid-flow intent switching

The original answer said this is "application-level orchestration" outside the graph. That's **partially correct**, but the real implementation is more nuanced:

**For mid-form intent (user types a message while the form is open):** The graph is paused at an `interrupt()`. We don't route to a separate agent — we resume the same interrupt with a special `{ action: "user_message", text: "..." }` payload. The node itself classifies the intent using an LLM and routes accordingly.

This means the subgraph handles its own escape hatches. It doesn't need the supervisor's help to understand "I want to go back to product search" — the `fill_form_node` classifies that intent internally and sets `current_step` to route to the right place.

**Why this works better than external orchestration:** The paused graph already has all the context — which product the user was filling the form for, what drafts have been completed, etc. Routing externally would lose this context or require complex state management to preserve it.

---

## Q2: Do subgraphs share the same thread_id with checkpointer?

> Does subgraphs reside under the same thread_id when using checkpointer mechanism?

### Revisited Answer

Yes. In our implementation, the parent graph uses `AsyncPostgresSaver` and the subgraph uses `checkpointer=True`:

```python
async def build_graph():
    checkpointer = await AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL).__aenter__()
    await checkpointer.setup()

    request_access_subgraph = build_request_access_subgraph().compile(checkpointer=True)

    builder = StateGraph(SupervisorState)
    builder.add_node("request_access", request_access_subgraph)
    graph = builder.compile(checkpointer=checkpointer)
```

#### What we learned in practice

1. **`checkpointer=True` is essential for multi-step flows.** The access request flow involves 5+ interrupt/resume cycles (domain selection, type selection, product selection, form filling per product, confirmation). Without `checkpointer=True`, the subgraph would lose its internal state between resume calls.

2. **PostgreSQL is non-negotiable for production.** We started with `InMemorySaver` for development and hit issues immediately — server restarts during testing wiped all conversation state. Switching to `AsyncPostgresSaver` early saved significant debugging time.

3. **Subgraph state inspection works.** We can inspect the full subgraph state (including `selected_products`, `form_drafts`, `current_step`) using `get_state(config, subgraphs=True)`. This was invaluable for debugging routing issues.

4. **The three-mode table from the original answer is accurate** (`checkpointer=False`, `None`, `True`). We use `True` for the request_access subgraph. FAQ and status_check don't need subgraphs at all — they're single nodes.

---

## Q3: Can subgraphs communicate directly with the user?

> Can subgraphs communicate directly to user? I intend the search and form to be interactive via an MCP App.

### Revisited Answer

Yes, through `interrupt()`. But the real story is **what goes into the interrupt payload** — this is the contract between the graph and the frontend.

#### What the interrupt payload actually looks like

Every interactive node emits a structured interrupt:

```python
form_data = interrupt({
    "type": "mcp_app",
    "resource_uri": "ui://question-form/mcp-app.html",
    "mcp_endpoint": "/mcp/question-form",
    "tool_name": "open-question-form",
    "tool_args": {"section": "ddf"},
    "context": {
        "selected_product": product,
        "draft_values": existing_draft,
        "product_type": "ddf",
        "product_index": 0,
        "total_products": 3,
    },
})
```

This payload is a self-describing instruction set. The frontend doesn't need any hardcoded knowledge of MCP servers — it reads the payload and dynamically:
1. Reads `mcp_endpoint` to know where to send JSON-RPC requests
2. Reads `resource_uri` to know which HTML resource to fetch
3. Reads `tool_name` / `tool_args` to know what tool call to forward
4. Reads `context` for any additional rendering context

#### The host acts as a generic MCP App runtime

The Angular `McpPanelComponent` is completely generic. It reacts to any `mcp_app` interrupt by:
1. Calling `resources/read` on the endpoint to fetch the HTML
2. Loading the HTML into a sandboxed iframe via `srcdoc`
3. Handling `postMessage` JSON-RPC communication (init, tool calls, messages)
4. Forwarding tool results from the MCP server to the iframe
5. Resuming the graph when the app sends a message back

Adding a new MCP App requires zero frontend changes — just register it in the backend `registry.py` and create a LangGraph node that emits the right interrupt.

#### Critical lesson: node re-execution on resume

The original answer warned about this, and it proved important. Every time the graph resumes at an interrupt, **all code before `interrupt()` re-runs**. Our `fill_form_node` handles this correctly — it reads the current product index from state and recalculates the section, which is idempotent. The actual side effects (saving form data) happen after `interrupt()` returns.

#### Non-MCP interrupts are simpler but follow the same pattern

Not every interrupt launches an MCP App. Simpler interactions use plain interrupts:

```python
# Facet selection — renders as buttons in the chat
response = interrupt({
    "type": "facet_selection",
    "facet": "domain",
    "message": "What domain are you interested in?",
    "options": [{"id": "clinical", "label": "Clinical"}, ...],
})

# Cart review — renders as a product list with action buttons
response = interrupt({
    "type": "cart_review",
    "products": products,
    "actions": [
        {"id": "fill_forms", "label": "Fill Access Forms"},
        {"id": "add_more", "label": "+ Add More Products"},
    ],
})
```

The frontend's `MessageComponent` reads the `type` field and renders the appropriate UI — buttons for facet selection, product cards for cart review, MCP panel for `mcp_app`.

---

## Q4: What if the MCP app is invoked from a subgraph node?

> I mean, the MCP app is invoked from one of the nodes on the subgraph.

### Revisited Answer

This is exactly how we built it. Both MCP Apps (question form and search) are invoked from subgraph nodes. The interrupt bubbles up through the parent graph to the API layer, which returns it to the frontend.

#### The full invocation chain

```
fill_form_node (subgraph) calls interrupt({type: "mcp_app", ...})
    ↓
LangGraph pauses the subgraph at the interrupt
    ↓
Parent graph invoke() returns with __interrupt__ in the result
    ↓
FastAPI endpoint extracts the interrupt and returns it as JSON
    ↓
Angular ChatService stores it in currentInterrupt signal
    ↓
McpPanelComponent effect() detects mcp_app type
    ↓
Panel opens, fetches HTML from /mcp/question-form, loads iframe
    ↓
Iframe initializes, host sends tool result via postMessage
    ↓
User fills form, app sends ui/message back
    ↓
Host calls ChatService.resumeWithData(formData)
    ↓
FastAPI /chat/resume calls graph.invoke(Command(resume=formData))
    ↓
fill_form_node's interrupt() returns with formData
    ↓
Node processes result and returns next state
```

#### Two communication protocols at different layers

This is a key architectural insight we discovered during implementation:

| Layer | Protocol | Transport | Purpose |
|:--|:--|:--|:--|
| Agent ↔ Frontend | REST + interrupt/resume | HTTP POST | Graph control flow |
| Host ↔ MCP App (iframe) | JSON-RPC 2.0 | `postMessage` | UI communication |

These are completely independent. The graph doesn't know about iframes or `postMessage`. The iframe doesn't know about LangGraph or interrupts. The `McpPanelComponent` bridges them.

#### MCP server mounting

The MCP servers are mounted as ASGI middleware on the FastAPI app, not as separate processes:

```python
MCP_APPS = [
    {"name": "question-form", "folder": "question-form-app-python"},
    {"name": "search-app",    "folder": "search-app"},
]

def mount_mcp_servers(app: FastAPI):
    prefixes = {f"/mcp/{a['name']}": a["name"] for a in MCP_APPS}
    # ASGI middleware intercepts /mcp/{name} and forwards to the MCP server
```

Each MCP server exposes:
- `resources/read` — returns the HTML for the MCP App
- `tools/call` — processes tool calls from the iframe (e.g., search, get form template)
- `tools/list` — lists available tools

#### What we'd do differently

The original answer correctly warned against hiding subgraphs inside tool functions. We followed this advice — `request_access` is a named subgraph node in the parent graph. This made state inspection and debugging straightforward.

---

## Q5: What if the user changes intent mid-MCP-interaction?

> What if in the middle of the interaction the user asks a question or intent switch?

### Revisited Answer

This was the hardest problem to solve correctly, and we went through three iterations.

#### Iteration 1: Ignore it (initial build)
The first version had no handling for free-text messages during an MCP App interrupt. The user could only interact through the MCP App UI. If they typed something in the chat, it was sent as a new message to the supervisor, which had no context about the paused flow and responded with confusion.

#### Iteration 2: Pattern matching on the frontend (fragile)
We added intent pattern matching in the Angular `ChatComponent`:

```typescript
const addMoreIntent = this.matchesIntent(lower, [
    'add more', 'add another', 'forgot to add', ...
]);
if (interruptType === 'mcp_app' && addMoreIntent) {
    this.addUserMessageAndResume(message, { action: 'add_more' });
    return;
}
```

This broke immediately. A user typing "can you go back to data product search" didn't match any pattern like "go back to select" or "back to products". Pattern matching against natural language is fundamentally brittle — there are infinite ways to express the same intent.

#### Iteration 3: LLM-based intent classification on the backend (current)

The final approach delegates **all** free-text messages during an MCP App interrupt to the backend, where an LLM classifies the intent:

**Frontend** — simple and generic:
```typescript
if (interruptType === 'mcp_app') {
    this.addUserMessageAndResume(message, { action: 'user_message', text: message });
    return;
}
```

**Backend** — LLM classification in the node itself:
```python
_INTENT_SYSTEM = SystemMessage(content="""\
Classify the user's message into exactly ONE of these intents:
- back_to_selection — wants to go back to reviewing/changing product selection
- add_more — wants to add more products without changing existing ones
- continue — wants to keep filling the form, or message is unrelated
Respond with ONLY the intent name.\
""")

_classifier_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

def _classify_form_intent(user_text: str) -> str:
    resp = _classifier_llm.invoke([_INTENT_SYSTEM, HumanMessage(content=user_text)])
    intent = resp.content.strip().lower()
    if intent in ("back_to_selection", "add_more"):
        return intent
    return "continue"
```

This handles any phrasing:
- "can you go back to data product search" → `back_to_selection`
- "take me back to where I pick products" → `back_to_selection`
- "I forgot to add the oncology dataset" → `add_more`
- "what does this field mean?" → `continue`

#### The key insight

The original answer suggested handling intent switches in the "client/gateway layer" with external orchestration. **That's wrong for our use case.** The right place to handle mid-flow intent is **inside the node**, because:

1. The node has the full graph state (which product, which form, what drafts exist)
2. The node can route within the subgraph using `current_step`
3. The LLM classification is fast (`gpt-4o-mini`, single prompt, ~200ms)
4. No state needs to be "passed externally" — it's all in the graph

The original answer's pseudocode with `classify_input()` in the client is only appropriate for truly cross-flow switches (e.g., user asks an FAQ question while filling a form). For navigation within the same flow, the subgraph handles it internally.

#### What about actual cross-flow switches?

For a genuine intent switch (e.g., user asks "what is the data steward approval process?" while filling a form), the current system sends it as `{ action: "user_message" }` and the classifier returns `continue` — the form stays open with a gentle nudge.

A future improvement could add a `faq_question` intent to the classifier and have the node answer the question inline (by calling the FAQ service) while keeping the form state intact, rather than routing the user away and losing their place.

---

## Q6: How should memory be managed for this pattern?

> What about memory management for this pattern?

### Revisited Answer

The three-layer model from the original answer is correct in principle. Here's what the actual implementation looks like:

#### Layer 1: Workflow state — what we actually track

```python
class SupervisorState(TypedDict):
    messages: Annotated[list, operator.add]
    active_intent: str
    thread_id: str
    user_id: str

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
    form_template: dict | None
```

Key design decisions that proved correct:
- **`selected_products` is a list, not a single product.** Multi-product selection was a requirement from day one.
- **`form_drafts` is a dict keyed by product ID.** This allows preserving drafts when the user navigates away and comes back.
- **`current_product_index` tracks form progress.** When filling forms for multiple products, this counter drives which product's form to show next.
- **`current_step` is the routing signal.** Every routing function checks this field to decide where to go.

#### Layer 2: Messages — what we keep lean

The original answer's advice to keep large payloads out of `messages` was critical. We put product data in `selected_products`, form data in `form_drafts`, and search results in `search_results`. Messages only contain:
- User natural-language turns
- Assistant response strings (summaries, prompts)
- `ToolMessage` ack objects for the supervisor's routing decisions

We do **not** put full product objects, form payloads, or search result lists in messages.

#### Layer 3: Long-term store — not yet implemented

We haven't implemented the cross-thread `Store` yet. For our current use case (single-session access requests), thread-scoped checkpointing is sufficient. But the original answer's candidates for long-term memory remain valid:
- User department (pre-fill facet selection)
- Preferred approver
- Common justification templates
- Previously accessed products

#### What we learned about PostgresSaver

```python
_checkpointer_ctx = AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL)
checkpointer = await _checkpointer_ctx.__aenter__()
await checkpointer.setup()
```

- `setup()` must be called once to create the checkpoint tables. Forgetting this causes silent failures.
- The async variant (`AsyncPostgresSaver`) is required with FastAPI's async endpoints.
- The context manager pattern (`__aenter__` / `__aexit__`) must be managed at the app lifecycle level (FastAPI startup/shutdown events).

#### The `form_drafts` pattern deserves special mention

One of the most valuable state design decisions was making `form_drafts` a dict keyed by product ID:

```python
form_drafts = {"dp-008": {purpose: "...", fields: {...}}, "dp-010": {...}}
```

This enables:
- **Draft preservation on navigation.** When the user goes back to product selection from the form, `form_drafts` is preserved in state. The `fill_form_node` explicitly returns `"form_drafts": form_drafts` in every exit path.
- **Pre-filling on re-entry.** When the user returns to a product they partially filled, the draft is passed as `context.draft_values` in the interrupt payload.
- **Cross-product data sharing.** A field like "purpose" filled on the cart screen can be injected into every product's draft before the form renders.

#### The `current_step` pattern

The most important state field is `current_step`. It's a string set by every node to signal where the graph should go next. The routing functions are simple switch statements on this field:

```python
def _route_after_fill_form(state):
    step = state.get("current_step", "")
    if step == "fill_form":    return "fill_form"
    if step == "narrow":       return "narrow"
    if step == "review_cart":  return "review_cart"
    return "confirm"
```

This pattern is more flexible than `add_edge()` chains and easier to reason about than complex conditional logic. Every node is responsible for setting `current_step` before returning, and every routing function is a pure function of state.

---

## Appendix: Architecture Patterns We Discovered

### Pattern 1: Interrupt payload as a contract

The interrupt payload is the API contract between the backend graph and the frontend. It must be self-describing:

```python
interrupt({
    "type": "mcp_app",              # tells the frontend WHAT to render
    "resource_uri": "ui://...",     # tells it WHERE to get the HTML
    "mcp_endpoint": "/mcp/...",     # tells it WHERE to send JSON-RPC
    "tool_name": "...",             # tells it WHICH tool to call
    "tool_args": {...},             # tells it WHAT arguments to pass
    "context": {...},               # gives it rendering context
})
```

This means adding a new MCP App requires zero frontend changes.

### Pattern 2: LLM classification at the interrupt boundary

Don't try to classify user intent in the frontend with pattern matching. Send the raw text to the backend and let the LLM classify it in the context of the current node:

```
Frontend: { action: "user_message", text: "<anything>" }
Backend:  _classify_form_intent(text) → back_to_selection | add_more | continue
```

Use `gpt-4o-mini` for classification — it's fast (~200ms), cheap, and accurate for simple intent classification.

### Pattern 3: Buttons for explicit actions, LLM for free text

The system has two input channels during an interrupt:
- **Buttons/UI actions** — deterministic, skip classification (`{ action: "add_more" }`)
- **Free text** — non-deterministic, needs LLM classification (`{ action: "user_message", text: "..." }`)

Both resume the same interrupt. The node handles both with a simple `if action ==` chain.

### Pattern 4: Two-protocol bridge

The `McpPanelComponent` bridges two completely independent protocols:

| Protocol | Direction | Transport | Used For |
|:--|:--|:--|:--|
| REST interrupt/resume | Frontend ↔ Backend | HTTP POST | Graph control flow |
| JSON-RPC 2.0 | Host ↔ Iframe | `postMessage` | MCP App communication |

The frontend is the adapter between them. The graph doesn't know about iframes. The iframe doesn't know about LangGraph.

### Pattern 5: ASGI middleware for MCP server mounting

MCP servers run in-process as ASGI middleware, not as separate services:

```python
def mount_mcp_servers(app: FastAPI):
    async def mcp_middleware(scope, receive, send):
        for prefix, name in prefixes.items():
            if path == prefix:
                rewritten_scope = {**scope, "path": "/mcp"}
                await manager.handle_request(rewritten_scope, receive, send)
                return
        await original_app(scope, receive, send)
    app.router = mcp_middleware
```

This avoids multi-process coordination, separate ports, and deployment complexity. Each MCP server is discovered at startup by the registry, initialized as a `StreamableHTTPSessionManager`, and served at `/mcp/{name}`.
