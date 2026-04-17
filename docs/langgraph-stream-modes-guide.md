# LangGraph Stream Modes — Implementation Guide

How to adopt all 7 LangGraph `stream_mode` options in this project's SSE streaming pipeline.

---

## Table of Contents

1. [Current Implementation](#current-implementation)
2. [All Stream Modes at a Glance](#all-stream-modes-at-a-glance)
3. [Mode 1: messages (already implemented)](#mode-1-messages-already-implemented)
4. [Mode 2: values](#mode-2-values)
5. [Mode 3: updates](#mode-3-updates)
6. [Mode 4: custom](#mode-4-custom)
7. [Mode 5: checkpoints](#mode-5-checkpoints)
8. [Mode 6: tasks](#mode-6-tasks)
9. [Mode 7: debug](#mode-7-debug)
10. [Using Multiple Modes Together](#using-multiple-modes-together)
11. [v2 Unified Format](#v2-unified-format)
12. [Subgraph Streaming](#subgraph-streaming)
13. [Recommended Integration Strategy](#recommended-integration-strategy)
14. [Backend Implementation Template](#backend-implementation-template)
15. [Frontend Implementation Template](#frontend-implementation-template)

---

## Current Implementation

The backend (`backend/app/service/chat_service.py`) currently uses:

```python
async for mode, chunk in self._graph.astream(
    input_data, config, stream_mode=["messages", "values"]
):
    if mode == "messages":
        token_chunk, _metadata = chunk
        if hasattr(token_chunk, "content") and token_chunk.content:
            yield {"event": "token", "data": {"token": token_chunk.content}}
```

**What works:** `messages` mode for LLM token streaming.
**What is ignored:** `values` chunks are received but silently dropped.
**What is missing:** `updates`, `custom`, `checkpoints`, `tasks`, `debug`.

The frontend (`frontend/client/src/app/core/services/chat.service.ts`) handles 4 SSE event names: `token`, `done`, `interrupt`, `error`.

---

## All Stream Modes at a Glance

| Mode | Chunk Shape | Use Case | Bandwidth |
|------|------------|----------|-----------|
| `messages` | `(BaseMessage, metadata_dict)` | Chat UIs, token-by-token streaming | Low |
| `values` | `dict` (full state) | State monitoring, debugging | High |
| `updates` | `dict` (node name -> delta) | Progress tracking, node-level updates | Medium |
| `custom` | `Any` (user-defined) | Progress bars, custom events | Low |
| `checkpoints` | `StateSnapshot` | Time travel, audit log | High |
| `tasks` | `dict` (task start/finish) | Execution monitoring, duration tracking | Medium |
| `debug` | `dict` (superset of checkpoints + tasks) | Development debugging | Very High |

---

## Mode 1: messages (already implemented)

Streams LLM tokens as they are generated, along with metadata about which node and model produced them.

### Native LangGraph usage

```python
async for chunk in graph.astream(
    {"messages": [HumanMessage("Hello")]},
    config,
    stream_mode="messages",
):
    token, metadata = chunk
    # token: AIMessageChunk with .content, .tool_calls, etc.
    # metadata: {"langgraph_node": "supervisor", "langgraph_step": 1, ...}
    if hasattr(token, "content") and token.content:
        print(token.content, end="", flush=True)
```

### Chunk shape

```python
(
    AIMessageChunk(content="Hello", id="run-abc123"),
    {
        "langgraph_node": "supervisor",
        "langgraph_step": 1,
        "langgraph_triggers": ["start:supervisor"],
        "langgraph_checkpoint_ns": "",
        "ls_model_name": "gpt-4o",
        "ls_provider": "openai",
    }
)
```

### What this project does with it

Extracts `token.content` and emits `event: token` / `data: {"token": "..."}` over SSE. The frontend appends each token to the last assistant message bubble for a typing effect.

---

## Mode 2: values

Emits the **complete graph state** after each node finishes executing. This includes all state fields (messages list, custom fields, etc.).

### Native LangGraph usage

```python
async for state in graph.astream(
    {"messages": [HumanMessage("Hello")]},
    config,
    stream_mode="values",
):
    # state is the full TypedDict after this step
    print(f"Messages so far: {len(state['messages'])}")
    print(f"Last message: {state['messages'][-1].content}")
```

### Chunk shape

```python
{
    "messages": [HumanMessage(...), AIMessage(...)],
    "thread_id": "abc-123",
    "user_id": "anonymous",
    # ... all other state fields
}
```

### When to use

- **State inspection:** See the full picture at each step during development.
- **Debugging:** Verify that state is being updated correctly across nodes.
- **Replay UIs:** Show a step-by-step state timeline.

### Caution

Every step emits the entire state, including the full message history. For conversations with many messages this generates significant bandwidth. Avoid sending to the browser in production unless the UI specifically needs it.

### SSE integration pattern

```python
# In chat_service.py stream loop:
if mode == "values":
    serializable = _serialize_state(chunk)  # convert messages to dicts
    yield {"event": "values", "data": serializable}
```

---

## Mode 3: updates

Emits **only the delta** returned by each node — the partial state update, keyed by node name.

### Native LangGraph usage

```python
async for update in graph.astream(
    {"messages": [HumanMessage("Hello")]},
    config,
    stream_mode="updates",
):
    for node_name, node_output in update.items():
        print(f"Node '{node_name}' returned: {node_output}")
```

### Chunk shape

```python
# After the "supervisor" node runs:
{
    "supervisor": {
        "messages": [AIMessage(content="I can help with that!")],
    }
}

# After the "search" node runs:
{
    "search": {
        "search_results": [{"id": "prod-1", "name": "Clinical Data"}],
    }
}
```

### When to use

- **Progress indicators:** Show which node is currently executing ("Searching...", "Reviewing cart...").
- **Incremental UI updates:** React to specific node outputs without waiting for the full state.
- **Node-level logging:** Track execution flow for analytics.

### SSE integration pattern

```python
if mode == "updates":
    for node_name, node_output in chunk.items():
        yield {
            "event": "updates",
            "data": {
                "node": node_name,
                "updates": _make_serializable(node_output),
            },
        }
```

### Frontend example

```typescript
case 'updates': {
    const { node, updates } = data;
    // e.g. show "Running: narrow" -> "Running: search" -> "Running: show_results"
    this.currentNode.set(node);
    break;
}
```

---

## Mode 4: custom

Emits **user-defined data** from inside any node or tool via `get_stream_writer()`. The writer is a callable that accepts any JSON-serializable value.

### Native LangGraph usage

```python
from langgraph.config import get_stream_writer

def search_node(state: AccessRequestState) -> dict:
    writer = get_stream_writer()

    writer({"type": "progress", "message": "Connecting to vector store..."})

    results = vector_search(state["query"])
    writer({"type": "progress", "message": f"Found {len(results)} results"})

    return {"search_results": results}
```

```python
async for chunk in graph.astream(
    input_data, config, stream_mode="custom"
):
    print(chunk)
    # {"type": "progress", "message": "Connecting to vector store..."}
    # {"type": "progress", "message": "Found 12 results"}
```

### Chunk shape

Whatever you pass to `writer()`. No wrapping — the value is emitted directly.

### When to use

- **Progress bars:** Emit percentage-complete updates from long-running nodes.
- **Status messages:** "Searching ChromaDB...", "Generating form...", "Submitting request...".
- **Custom metrics:** Emit timing, token counts, or cost data.
- **Structured events:** Application-specific events that don't fit the state model.

### SSE integration pattern

```python
if mode == "custom":
    yield {"event": "custom", "data": chunk}
```

### Frontend example

```typescript
case 'custom': {
    // data is whatever the node emitted
    if (data.type === 'progress') {
        this.progressMessage.set(data.message);
    }
    break;
}
```

### Important note

`get_stream_writer()` is a **no-op** when the graph is invoked with `ainvoke()` or when `custom` is not in the `stream_mode` list. You can safely add writer calls to nodes without breaking non-streaming paths.

---

## Mode 5: checkpoints

Emits a **state snapshot** every time the checkpointer saves state. The shape matches what `graph.aget_state(config)` returns.

### Native LangGraph usage

```python
async for snapshot in graph.astream(
    input_data, config, stream_mode="checkpoints"
):
    print(f"Step: {snapshot.metadata['step']}")
    print(f"Node: {snapshot.metadata.get('source', 'N/A')}")
    print(f"State keys: {list(snapshot.values.keys())}")
    print(f"Pending tasks: {len(snapshot.tasks)}")
```

### Chunk shape

```python
StateSnapshot(
    values={"messages": [...], "thread_id": "..."},
    next=("supervisor",),
    config={"configurable": {"thread_id": "abc", "checkpoint_id": "..."}},
    metadata={"source": "loop", "step": 3, "writes": {...}},
    created_at="2026-04-15T10:30:00Z",
    parent_config={...},
    tasks=(PregelTask(...),),
)
```

### When to use

- **Time travel UI:** Let users rewind and inspect previous states.
- **Audit trail:** Log every checkpoint for compliance.
- **Debugging:** Inspect exactly what was saved at each step.

### Caution

Checkpoints contain the full state and internal metadata. This is sensitive data — do not expose to the browser in production without filtering.

### SSE integration pattern

```python
if mode == "checkpoints":
    yield {
        "event": "checkpoints",
        "data": {
            "step": snapshot.metadata.get("step"),
            "source": snapshot.metadata.get("source"),
            "node": snapshot.metadata.get("source"),
            "next": list(snapshot.next),
            "checkpoint_id": snapshot.config["configurable"].get("checkpoint_id"),
        },
    }
```

---

## Mode 6: tasks

Emits events when **tasks start and finish**, including results and errors. Useful for monitoring execution timing.

### Native LangGraph usage

```python
async for event in graph.astream(
    input_data, config, stream_mode="tasks"
):
    print(event)
```

### Chunk shape

```python
# Task start:
{
    "type": "task_start",
    "name": "supervisor",
    "id": "task-abc-123",
}

# Task finish:
{
    "type": "task_end",
    "name": "supervisor",
    "id": "task-abc-123",
    "result": {"messages": [AIMessage(...)]},
    "error": None,
}
```

### When to use

- **Execution timeline:** Show how long each node took.
- **Error tracking:** Detect which node failed and why.
- **Performance monitoring:** Identify bottleneck nodes.

### SSE integration pattern

```python
if mode == "tasks":
    yield {
        "event": "tasks",
        "data": _make_serializable(chunk),
    }
```

---

## Mode 7: debug

A **superset** of `checkpoints` + `tasks` with additional metadata. Emits the most verbose information possible.

### Native LangGraph usage

```python
async for event in graph.astream(
    input_data, config, stream_mode="debug"
):
    print(f"Debug event type: {event.get('type', 'unknown')}")
    print(f"Step: {event.get('step', 'N/A')}")
```

### Chunk shape

Varies — combines checkpoint and task payloads with extra fields like full node inputs/outputs, timing, and step metadata.

### When to use

- **Development only.** This is the kitchen-sink mode for troubleshooting.
- Generates the most data of any mode — never use in production.

### SSE integration pattern

```python
if mode == "debug":
    yield {
        "event": "debug",
        "data": _make_serializable(chunk),
    }
```

---

## Using Multiple Modes Together

Pass a list to `stream_mode` to receive multiple modes simultaneously. When using multiple modes, each chunk is a `(mode, data)` tuple:

```python
async for mode, chunk in graph.astream(
    input_data, config,
    stream_mode=["messages", "updates", "custom"],
):
    if mode == "messages":
        token, metadata = chunk
        # handle token
    elif mode == "updates":
        for node_name, output in chunk.items():
            # handle node update
    elif mode == "custom":
        # handle custom data
```

When using a **single** mode (string, not list), chunks are the raw data without the mode prefix:

```python
# Single mode — chunks are NOT tuples
async for chunk in graph.astream(input_data, config, stream_mode="updates"):
    # chunk is the update dict directly, not (mode, dict)
    for node_name, output in chunk.items():
        ...
```

---

## v2 Unified Format

LangGraph >= 1.1 supports `version="v2"` which wraps every chunk in a consistent `StreamPart` dict regardless of mode:

```python
async for part in graph.astream(
    input_data, config,
    stream_mode=["messages", "updates", "custom"],
    version="v2",
):
    # part is always a dict with "type" and "data" keys
    if part["type"] == "messages":
        token, metadata = part["data"]
    elif part["type"] == "updates":
        node_name, output = list(part["data"].items())[0]
    elif part["type"] == "custom":
        custom_data = part["data"]
```

### StreamPart TypedDicts

```python
from langgraph.types import (
    ValuesStreamPart,
    UpdatesStreamPart,
    MessagesStreamPart,
    CustomStreamPart,
    CheckpointStreamPart,
    TasksStreamPart,
    DebugStreamPart,
)
```

### When to adopt v2

- Simplifies the dispatch logic (no `(mode, chunk)` tuple unpacking).
- Enables type narrowing via `part["type"]`.
- Recommended for new projects; this project can migrate when convenient.

---

## Subgraph Streaming

By default, events from subgraphs (like `request_access`) are **not** included. Pass `subgraphs=True` to include them:

```python
async for namespace, mode, chunk in graph.astream(
    input_data, config,
    stream_mode=["messages", "updates"],
    subgraphs=True,
):
    # namespace: tuple of subgraph names, e.g. ("request_access",)
    # empty tuple () means the parent graph
    if namespace:
        print(f"Subgraph {namespace}: {mode}")
    else:
        print(f"Parent graph: {mode}")
```

This is useful for showing progress within the request access subgraph (e.g., which node is currently executing: narrow -> search -> show_results -> review_cart).

---

## Recommended Integration Strategy

### Do NOT enable all modes at once

Enabling all 7 modes simultaneously is wasteful and insecure:

- `values` emits the full state (including entire message history) after every step.
- `debug` is a superset of `checkpoints` + `tasks` — redundant if both are enabled.
- `values`, `checkpoints`, and `debug` expose internal graph state to the browser.

### Make stream_modes configurable per request

Add an optional `stream_modes` field to the request body so the frontend can opt in to exactly what it needs:

```python
# backend/app/schema/chat.py
class ChatRequest(BaseModel):
    action: Literal["send", "resume"] = "send"
    message: str = ""
    resume_data: dict = Field(default_factory=dict)
    thread_id: str = Field(default="")
    user_id: str = Field(default="anonymous")
    stream_modes: list[str] = Field(default_factory=lambda: ["messages"])
```

Default is `["messages"]` — identical to current behavior. No breaking changes.

### Adopt modes incrementally

| Feature Need | Add Mode | Priority |
|-------------|----------|----------|
| Token streaming (done) | `messages` | Already implemented |
| "Running: search..." progress | `updates` | Next |
| Custom progress bars / status | `custom` | Next |
| Step-by-step state timeline | `values` | Later |
| Execution timing analytics | `tasks` | Later |
| Dev-only debugging panel | `debug` | Later |
| Time travel / audit | `checkpoints` | Later |

---

## Backend Implementation Template

When ready to implement, here is the full `stream()` method pattern that handles all modes:

```python
from langgraph.config import get_stream_writer  # for custom mode in nodes

VALID_STREAM_MODES = {"values", "updates", "messages", "custom", "checkpoints", "tasks", "debug"}

async def stream(
    self, *, action: str, message: str, resume_data: dict,
    thread_id: str, user_id: str,
    stream_modes: list[str] | None = None,
) -> AsyncIterator[dict]:
    input_data, thread_id = self._build_input(
        action=action, message=message, resume_data=resume_data,
        thread_id=thread_id, user_id=user_id,
    )
    config = {"configurable": {"thread_id": thread_id}}

    modes = list(set(stream_modes or ["messages"]) & VALID_STREAM_MODES)
    if "messages" not in modes:
        modes.append("messages")  # always need token streaming

    full_content = ""

    async for mode, chunk in self._graph.astream(
        input_data, config, stream_mode=modes
    ):
        if mode == "messages":
            token_chunk, _metadata = chunk
            if hasattr(token_chunk, "content") and token_chunk.content:
                full_content += token_chunk.content
                yield {"event": "token", "data": {"token": token_chunk.content}}

        elif mode == "updates":
            for node_name, node_output in chunk.items():
                yield {
                    "event": "updates",
                    "data": {"node": node_name, "updates": _make_serializable(node_output)},
                }

        elif mode == "values":
            yield {"event": "values", "data": _make_serializable(chunk)}

        elif mode == "custom":
            yield {"event": "custom", "data": chunk}

        elif mode == "checkpoints":
            yield {
                "event": "checkpoints",
                "data": {
                    "step": chunk.metadata.get("step"),
                    "next": list(chunk.next),
                    "checkpoint_id": chunk.config["configurable"].get("checkpoint_id"),
                },
            }

        elif mode == "tasks":
            yield {"event": "tasks", "data": _make_serializable(chunk)}

        elif mode == "debug":
            yield {"event": "debug", "data": _make_serializable(chunk)}

    # Post-stream interrupt check (unchanged)
    state = await self._graph.aget_state(config)
    if state.tasks:
        for task in state.tasks:
            if task.interrupts:
                interrupt_val = task.interrupts[0].value
                yield {
                    "event": "interrupt",
                    "data": {
                        "type": "interrupt",
                        "interrupt_value": interrupt_val,
                        "thread_id": thread_id,
                    },
                }
                return

    yield {
        "event": "done",
        "data": {"type": "message", "content": full_content, "thread_id": thread_id},
    }
```

Helper for serializing LangChain objects:

```python
def _make_serializable(obj: Any) -> Any:
    """Convert LangChain messages and other non-serializable objects to dicts."""
    if hasattr(obj, "dict"):
        return obj.dict()
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(item) for item in obj]
    return obj
```

---

## Frontend Implementation Template

### TypeScript interfaces

```typescript
// Add to core/models/chat.model.ts

export type StreamMode = 'values' | 'updates' | 'messages' | 'custom' | 'checkpoints' | 'tasks' | 'debug';

export interface SSEValuesEvent {
  [key: string]: unknown;
}

export interface SSEUpdatesEvent {
  node: string;
  updates: Record<string, unknown>;
}

export interface SSECustomEvent {
  [key: string]: unknown;
}

export interface SSECheckpointEvent {
  step: number;
  next: string[];
  checkpoint_id: string;
}

export interface SSETasksEvent {
  type: string;
  name: string;
  id: string;
  result?: Record<string, unknown>;
  error?: string;
}

export interface SSEDebugEvent {
  [key: string]: unknown;
}
```

### Handler switch cases

```typescript
// Add to handleSSEEvent() in chat.service.ts

case 'updates': {
    const { node } = data as SSEUpdatesEvent;
    console.debug('[stream] node update:', node);
    // Future: this.currentNode.set(node);
    break;
}
case 'custom': {
    console.debug('[stream] custom event:', data);
    // Future: this.customEvent.set(data);
    break;
}
case 'values': {
    console.debug('[stream] full state snapshot');
    break;
}
case 'checkpoints': {
    console.debug('[stream] checkpoint:', data);
    break;
}
case 'tasks': {
    console.debug('[stream] task event:', data);
    break;
}
case 'debug': {
    console.debug('[stream] debug event:', data);
    break;
}
```

### Requesting specific modes

```typescript
await this.streamRequest({
    action: 'send',
    message: content,
    thread_id: this.threadId(),
    user_id: 'anonymous',
    stream_modes: ['messages', 'updates'],  // opt-in to updates
});
```
