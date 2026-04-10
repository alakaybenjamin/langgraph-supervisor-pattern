# Validated Answers — Data Governance Chat with LangGraph

Answers to each question from the original Perplexity transcript, validated and corrected against the official LangGraph skill documentation (`langgraph-fundamentals`, `langgraph-persistence`, `langgraph-human-in-the-loop`).

---

## Q1: Which agentic pattern should I use?

> I have a chat interface for a data governance app. Based on inferred user intent it must route to one of 3 flows:
> 1. Request access to data product (search → select → fill form → submit)
> 2. Information Q&A on the request access process
> 3. Check status of existing request
>
> My framework of choice is LangGraph. Which agentic pattern must I use?
>
> Considerations:
> a. What if the user in the middle of flow 1 asks a question intended for flow 2?
> b. What if the user in the middle of flow 1 wants to check status?

### Answer

Use a **supervisor node with `Command`-based routing**, a **stateful subgraph** for the multi-step access request flow, and **simple tool-calling nodes** for FAQ and status checks.

#### Why `Command`

`Command` is the LangGraph primitive that combines a state update and a routing decision in a single return value:

```python
from langgraph.types import Command
from typing import Literal

def supervisor(state: State) -> Command[Literal["request_access", "faq", "status_check"]]:
    intent = classify_intent(state["messages"][-1])
    return Command(
        update={"active_intent": intent},
        goto=intent
    )
```

The `Command[Literal[...]]` return type annotation declares the valid routing destinations. LangGraph uses this to build the graph edges automatically.

The fundamentals skill defines the edge selection logic:

| Need | Edge Type | When to Use |
|:--|:--|:--|
| Always go to same node | `add_edge()` | Fixed, deterministic flow |
| Route based on state | `add_conditional_edges()` | Dynamic branching |
| **Update state AND route** | **`Command`** | **Combine logic in single node** |
| Fan-out to multiple nodes | `Send` | Parallel processing |

`Command` is the right choice for the supervisor because it needs to both update which flow is active *and* route to the correct node.

#### Critical warning: `Command` + static edges

> `Command` only adds **dynamic** edges — static edges defined with `add_edge` still execute. If `node_a` returns `Command(goto="node_c")` and you also have `graph.add_edge("node_a", "node_b")`, **both** `node_b` and `node_c` will run.

This means the supervisor node must **not** have any `add_edge()` calls pointing away from it. Use only `Command` returns for routing.

#### Why a subgraph for flow 1

Flow 1 (request access) is multi-step and stateful: search → select → fill form → submit. This should be a **subgraph** with explicit nodes for each step:

```python
from langgraph.graph import StateGraph, START, END

class AccessRequestState(TypedDict):
    messages: Annotated[list, operator.add]
    current_step: str
    selected_product: dict | None
    form_draft: dict | None

def search_products(state: AccessRequestState) -> dict:
    # Emit structured UI request, pause for user interaction
    result = interrupt({
        "ui": "data_product_search",
        "filters": state.get("search_filters", {})
    })
    return {"selected_product": result, "current_step": "fill_form"}

access_request_graph = (
    StateGraph(AccessRequestState)
    .add_node("search", search_products)
    .add_node("fill_form", fill_form_step)
    .add_node("confirm", confirm_submission)
    .add_node("submit", submit_request)
    .add_edge(START, "search")
    .add_conditional_edges("search", route_after_search)
    .add_edge("fill_form", "confirm")
    .add_conditional_edges("confirm", route_after_confirm)
    .add_edge("submit", END)
    .compile()
)
```

#### Why simple nodes for flows 2 and 3

FAQ and status check are short, mostly stateless operations. They don't need their own subgraphs — a single node that calls a tool or LLM is sufficient:

```python
def faq_node(state: State) -> dict:
    answer = llm_with_rag.invoke(state["messages"])
    return {"messages": [answer]}

def status_check_node(state: State) -> dict:
    status = lookup_request_status(state["user_id"])
    return {"messages": [AIMessage(content=f"Your request status: {status}")]}
```

#### Full graph structure

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

parent_graph = (
    StateGraph(SupervisorState)
    .add_node("supervisor", supervisor)
    .add_node("request_access", access_request_graph)  # subgraph as node
    .add_node("faq", faq_node)
    .add_node("status_check", status_check_node)
    .add_edge(START, "supervisor")
    # No add_edge from supervisor — Command handles routing
    .add_edge("faq", "supervisor")         # Return to supervisor after FAQ
    .add_edge("status_check", "supervisor") # Return to supervisor after status
    .add_edge("request_access", END)        # Complete after submission
    .compile(checkpointer=InMemorySaver())
)
```

#### Handling consideration (a): mid-flow FAQ question

When the user is in flow 1 and asks a process question, the subgraph is paused at an `interrupt()`. The client classifies the new message as an FAQ question and handles it **outside** the graph run, or routes it through a separate invocation. After the FAQ is answered, the client sends `Command(resume=...)` to the original interrupt to continue the access request flow.

This is **application-level orchestration** — LangGraph does not have a built-in "pause subgraph A, run agent B, resume subgraph A" primitive. What it provides is:

- `interrupt()` to pause
- Checkpointed state that persists the pause point
- `Command(resume=...)` to continue later

The routing logic between "this is a form submission" vs "this is a side question" is your client/gateway code.

#### Handling consideration (b): mid-flow status check

Same mechanism as (a). The access request subgraph remains paused. The status check runs as a separate operation. After showing status, the client asks the user whether to resume the access request and either sends `Command(resume=...)` or abandons the paused flow.

A practical state design for tracking paused flows:

```python
class SupervisorState(TypedDict):
    messages: Annotated[list, operator.add]
    active_intent: str
    paused_flow: str | None       # e.g. "request_access"
    paused_step: str | None       # e.g. "fill_form"
    resume_available: bool
```

---

## Q2: Do subgraphs share the same thread_id with checkpointer?

> Does subgraphs reside under the same thread_id when using checkpointer mechanism?

### Answer

Yes, subgraphs execute under the parent's `thread_id`. But **how** persistence works depends on the subgraph's `checkpointer` parameter at compile time. There are **three modes**, not two:

| Feature | `checkpointer=False` | `None` (default, omit) | `True` |
|:--|:--|:--|:--|
| Interrupts (HITL) | No | **Yes** | Yes |
| Multi-turn memory | No | **No** | **Yes** |
| Same subgraph called in parallel | Yes | Yes | **No** (namespace conflict) |
| State inspection | No | Current invocation only | Full |

#### When to use each mode

- **`checkpointer=False`** — Subgraph doesn't need interrupts or persistence. No checkpoint overhead.
- **`None` (default)** — Subgraph needs `interrupt()` but not multi-turn memory. Each invocation starts fresh but can pause/resume. This is the right choice if the subgraph completes within a single parent invocation cycle.
- **`checkpointer=True`** — Subgraph needs to remember state across multiple parent invocations. Each call picks up where the last left off. Use this for the request-access flow where the user interacts across multiple interrupt/resume cycles.

```python
# For the request-access subgraph that needs multi-step memory:
access_request_graph = subgraph_builder.compile(checkpointer=True)

# For a simple utility subgraph with no interrupt needs:
utility_graph = subgraph_builder.compile(checkpointer=False)
```

#### Practical rules

1. Pass the checkpointer to the **parent** graph at compile time.
2. Choose the subgraph's checkpointer mode based on its needs (not blanket "inherit").
3. Do **not** run the same stateful subgraph (`checkpointer=True`) instance multiple times in parallel within one node — the calls write to the same checkpoint namespace and conflict.
4. Use `graph.get_state(config, subgraphs=True)` to inspect subgraph state under the same parent thread.

```python
config = {"configurable": {"thread_id": "session-1"}}
state = parent_graph.get_state(config, subgraphs=True)
```

---

## Q3: Can subgraphs communicate directly with the user?

> Can subgraphs communicate directly to user? I intend the search and form to be interactive via an MCP App.

### Answer

A subgraph communicates with the user **through `interrupt()`**, which propagates upward to the top-level caller. The user interaction boundary is always the parent graph's `invoke()`/`stream()` call.

#### The mechanism

```python
from langgraph.types import interrupt, Command

def search_step(state: AccessRequestState):
    # Pause and request MCP UI rendering
    user_response = interrupt({
        "ui_mode": "data_product_search",
        "filters": state.get("search_filters", {}),
        "title": "Search Data Products"
    })
    return {"selected_product": user_response["product"]}
```

When the graph hits `interrupt()`:
1. Execution pauses.
2. The interrupt value surfaces in the result under `__interrupt__`.
3. Your MCP App host reads the interrupt payload, renders the appropriate UI.
4. The user interacts with the MCP App (search, select, fill form).
5. The client resumes the graph with `Command(resume=structured_result)`.
6. The `interrupt()` call returns the resume value and the node continues.

```python
config = {"configurable": {"thread_id": "session-1"}}

# Step 1: Graph pauses at search_step's interrupt()
result = parent_graph.invoke({"messages": [...]}, config)
# result["__interrupt__"] = [Interrupt(value={"ui_mode": "data_product_search", ...})]

# Step 2: MCP App renders search UI, user selects a product

# Step 3: Resume with the user's selection
result = parent_graph.invoke(
    Command(resume={"product": {"id": "prod-123", "name": "Customer Data"}}),
    config
)
```

#### Critical: node re-execution on resume

> **When the graph resumes, the node restarts from the beginning — ALL code before `interrupt()` re-runs. In subgraphs, BOTH the parent node and the subgraph node re-execute.**

This means:

```python
def search_step(state: AccessRequestState):
    log_search_attempt()     # <-- THIS RUNS AGAIN on every resume
    results = call_api()     # <-- THIS RUNS AGAIN on every resume
    user_response = interrupt({"results": results})
    return {"selected_product": user_response}
```

**Rules for code before `interrupt()`:**
- Use **upsert** (not insert) operations — idempotent
- Use **check-before-create** patterns
- Place side effects **after** `interrupt()` when possible
- Separate non-idempotent side effects into their own preceding node

```python
# SAFE: side effect after interrupt
def search_step(state: AccessRequestState):
    user_response = interrupt({
        "ui_mode": "data_product_search",
        "cached_results": state.get("search_results", [])
    })
    log_product_selected(user_response["product"])  # Only runs once
    return {"selected_product": user_response["product"]}
```

#### MCP App integration pattern

The MCP App should return **structured events**, not raw text:

| Event | Meaning | Graph action |
|:--|:--|:--|
| `SEARCH_SELECTED` | User picked a product | `Command(resume={"product": ...})` |
| `FORM_SUBMITTED` | User completed the form | `Command(resume={"form_data": ...})` |
| `USER_ASKED_QUESTION` | User typed a side question | Route to FAQ externally, then resume |
| `USER_CANCELED` | User abandoned the flow | Do not resume; start fresh |

---

## Q4: What if the MCP app is invoked from a subgraph node?

> I mean, the MCP app is invoked from one of the nodes on the subgraph.

### Answer

Yes, a subgraph node can trigger an MCP App. There are two patterns depending on whether the MCP call needs user interaction:

#### Pattern 1: Machine-only MCP call (no user interaction)

If the MCP server returns data synchronously (e.g., a backend search API), treat it as a regular node operation:

```python
def search_products_node(state: AccessRequestState) -> dict:
    results = mcp_client.call_tool("search-data-products", {
        "query": state["search_query"]
    })
    return {"search_results": results}
```

No `interrupt()` needed. The node runs to completion.

#### Pattern 2: Interactive MCP App (needs user input)

If the MCP App renders a UI and needs user interaction, use `interrupt()`:

```python
def fill_form_node(state: AccessRequestState) -> dict:
    # Interrupt with the payload the MCP App needs to render the form
    form_result = interrupt({
        "ui_mode": "question_form",
        "template": state["form_template"],
        "draft_values": state.get("form_draft", {}),
        "selected_product": state["selected_product"]
    })
    return {"form_draft": form_result, "current_step": "confirm"}
```

**Do not** make the MCP App a blocking tool call that waits for the user. This breaks checkpointing, makes retries unsafe, and prevents mid-flow intent switching.

#### What to avoid

Do not bury the subgraph inside a tool function. If the access flow is central and interactive, make it a **real subgraph node** under the parent graph:

```python
# GOOD: Subgraph as a named node — state inspection works
parent_builder.add_node("request_access", access_request_subgraph)

# AVOID: Subgraph hidden inside a tool — state inspection breaks
@tool
def request_access_tool(query: str):
    return access_request_subgraph.invoke({"query": query})
parent_builder.add_node("tools", ToolNode([request_access_tool]))
```

The persistence skill notes that viewing subgraph state does not work when the subgraph is invoked through indirect tool calls.

---

## Q5: What if the user changes intent mid-MCP-interaction?

> What if in the middle of the interaction the user asks a question or intent switch?

### Answer

When the MCP App is open and the graph is paused at an `interrupt()`, the system should distinguish between:

| User action | Classification | System behavior |
|:--|:--|:--|
| Submits search/form data | Resume payload | `Command(resume=structured_data)` — graph continues |
| Asks "What does steward approval mean?" | Clarifying FAQ | Handle externally, then prompt to resume |
| Says "Check my request status" | Intent switch | Run status check, preserve paused state for later |
| Says "Cancel" | Abandonment | Do not resume; close the paused flow |

#### How to implement this

LangGraph does **not** have a built-in "pause flow A, run flow B, resume flow A" primitive. The orchestration logic lives in your **client/gateway layer**:

```python
# Client-side pseudocode
while True:
    user_input = get_user_input()
    
    if graph_is_paused:
        input_type = classify_input(user_input, paused_context)
        
        if input_type == "resume_payload":
            # User interacted with MCP App — resume the paused graph
            result = graph.invoke(Command(resume=user_input.payload), config)
            
        elif input_type == "faq_question":
            # Side question — answer without touching the graph
            answer = faq_agent.invoke(user_input)
            display(answer)
            display("Would you like to continue your access request?")
            
        elif input_type == "status_check":
            # Intent switch — run status, keep graph paused
            status = status_agent.invoke(user_input)
            display(status)
            display("You have a draft access request in progress. Continue?")
            
        elif input_type == "cancel":
            # Abandon the paused flow
            paused_context = None
    else:
        # No paused graph — route normally through supervisor
        result = graph.invoke({"messages": [user_input]}, config)
```

#### State design for resumability

```python
class SupervisorState(TypedDict):
    messages: Annotated[list, operator.add]
    active_intent: str
    # Paused flow tracking
    paused_flow: str | None            # "request_access"
    paused_step: str | None            # "fill_form"
    form_draft: dict | None            # Preserved draft data
    selected_product: dict | None      # Preserved selection
    resume_available: bool
```

The checkpointer preserves the graph's paused state (including the exact interrupt point in the subgraph), so `Command(resume=...)` will pick up exactly where it left off — but only for the paused flow. The FAQ/status handling happens outside the paused graph run.

---

## Q6: How should memory be managed for this pattern?

> What about memory management for this pattern?

### Answer

Use **three layers** of memory, each with its own LangGraph mechanism:

#### Layer 1: Workflow state (checkpointer, thread-scoped)

For everything needed to **resume the in-flight workflow**. Stored in the graph's `State` and persisted by the checkpointer under a `thread_id`.

```python
from typing_extensions import TypedDict, Annotated
import operator

class WorkflowState(TypedDict):
    messages: Annotated[list, operator.add]
    active_intent: str
    current_step: str
    selected_product: dict | None
    form_draft: dict | None
    search_results: list
    pending_interrupt: dict | None
    paused_flow: str | None
```

**Rules:**
- If losing it would break **resume**, it goes in checkpointed state.
- Do **not** overload the `messages` list with large payloads (form drafts, search results, product catalogs). Those belong in dedicated state fields.
- Always provide `thread_id`:

```python
config = {"configurable": {"thread_id": "session-1"}}
result = graph.invoke({"messages": [...]}, config)
```

Without `thread_id`, state is not persisted between invocations.

#### Layer 2: Conversation history (checkpointer, thread-scoped)

The `messages` field with a reducer (`Annotated[list, operator.add]`). Keep this lean:

- **Put in messages**: user natural-language turns, assistant responses, compact summaries of workflow actions.
- **Keep out of messages**: full form payloads, search result lists, product catalogs, MCP App event envelopes, large API responses.

Summarize older turns aggressively, but **never summarize away exact form draft fields** unless they are copied into structured state fields.

#### Layer 3: Long-term memory (Store, cross-thread)

For facts worth remembering across conversations. The Store is a separate persistence mechanism from the checkpointer:

```python
from langgraph.store.memory import InMemoryStore
from langgraph.runtime import Runtime

store = InMemoryStore()

# Save a user preference
store.put(("user-123", "preferences"), "department", {"value": "R&D"})

# Access store inside a node via Runtime
def personalized_node(state: State, runtime: Runtime):
    prefs = runtime.store.get((state["user_id"], "preferences"), "department")
    department = prefs.value["value"] if prefs else "Unknown"
    return {"department": department}

# Compile with both checkpointer and store
graph = builder.compile(checkpointer=checkpointer, store=store)
```

**Good long-term memory candidates:**
- User department or business unit
- Preferred approver or common justification templates
- Accessibility or UX preferences
- Repeated product interests

**Bad candidates (keep in thread state instead):**
- Current form draft
- Current paused step
- Latest search results
- Temporary status check results

#### Store operations

```python
store.put(("user-123", "facts"), "location", {"city": "London"})       # Put
item = store.get(("user-123", "facts"), "location")                     # Get
results = store.search(("user-123", "facts"), filter={"city": "London"}) # Search
store.delete(("user-123", "facts"), "location")                         # Delete
```

#### Access pattern inside nodes

Access the store via the `Runtime` parameter, not by importing it directly:

```python
from langgraph.runtime import Runtime

# WRONG — store not available
def my_node(state):
    store.put(...)  # NameError!

# CORRECT — access via runtime
def my_node(state, runtime: Runtime):
    runtime.store.put(...)
```

#### Production considerations

| Component | Development | Production |
|:--|:--|:--|
| Checkpointer | `InMemorySaver()` | `PostgresSaver` |
| Store | `InMemoryStore()` | `PostgresStore` |

`InMemorySaver` and `InMemoryStore` lose all data on process restart. Always use PostgreSQL-backed storage in production:

```python
from langgraph.checkpoint.postgres import PostgresSaver

with PostgresSaver.from_conn_string("postgresql://user:pass@localhost/db") as checkpointer:
    checkpointer.setup()  # Only needed on first run to create tables
    graph = builder.compile(checkpointer=checkpointer, store=production_store)
```

#### Rule of thumb

| If the data... | Store it in... |
|:--|:--|
| Is needed to **resume** the workflow | Checkpointed **state** |
| Should survive across **conversations** | Long-term **store** |
| Only helps the model speak naturally | Compact form in **messages** |

---

## Appendix: Key LangGraph Patterns Reference

### State with reducers

```python
from typing_extensions import TypedDict, Annotated
import operator

class State(TypedDict):
    name: str                                  # Overwrites on update
    messages: Annotated[list, operator.add]     # Appends to list
    total: Annotated[int, operator.add]         # Sums integers
```

Without a reducer, returning a list **overwrites** previous values — previous data is lost.

### Node return values

Nodes must return **partial update dicts**, not the full state:

```python
# WRONG
def my_node(state: State) -> State:
    state["field"] = "updated"
    return state

# CORRECT
def my_node(state: State) -> dict:
    return {"field": "updated"}
```

### Interrupt + resume

```python
from langgraph.types import interrupt, Command

def approval_node(state: State):
    decision = interrupt({"message": "Approve this action?", "draft": state["draft"]})
    if decision["approved"]:
        return Command(update={"approved": True}, goto="execute")
    return Command(update={}, goto="__end__")

# Invoke — pauses at interrupt
result = graph.invoke({"draft": "..."}, config)

# Resume — provides the human's response
result = graph.invoke(Command(resume={"approved": True}), config)
```

### Compile with persistence

```python
from langgraph.checkpoint.memory import InMemorySaver

graph = builder.compile(checkpointer=InMemorySaver())

config = {"configurable": {"thread_id": "session-1"}}
graph.invoke({"messages": ["Hello"]}, config)
graph.invoke({"messages": ["What did I say?"]}, config)  # Remembers
```

### Time travel

```python
states = list(graph.get_state_history(config))
past = states[-2]
result = graph.invoke(None, past.config)  # Replay from past checkpoint
```
