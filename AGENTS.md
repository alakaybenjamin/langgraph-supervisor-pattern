# AGENTS.md — LangGraph Supervisor Pattern

This file provides context for AI agents working on this codebase.

## Project Overview

A **Data Governance Chat Application** that demonstrates the **LangGraph Supervisor Pattern** — a parent supervisor LLM routes user intent to specialized siblings (a request-access workflow subgraph and several FAQ / status agents) using gpt-4o tool-calling. Interactive MCP (Model Context Protocol) Apps render rich UI inline within the conversation.

### Architecture at a Glance

```
User <-> Angular SPA <-> Express BFF <-> FastAPI Backend
                                              |
                                       LangGraph Parent Graph
                                              |
                                       recover_state
                                              |
                                       supervisor_router  (gpt-4o classifier)
                          /          /          \           \
            request_access     faq_kb_agent  general_faq   status_agent
              subgraph          (KB / IHD)   _tavily_agent  (in-memory)
              (compiled                       (web FAQ)
               StateGraph
               attached as
               a node)
                  |
              MCP Apps (search-app, question-form-app-python)
```

## Directory Structure

```
├── backend/                    # Python FastAPI + LangGraph backend
│   ├── app/
│   │   ├── main.py             # FastAPI entry point, lifespan events
│   │   ├── api/routes/         # REST endpoints (chat, health)
│   │   ├── core/               # Config (pydantic-settings), LLM factory, logging
│   │   ├── db/                 # SQLAlchemy async session, Alembic integration
│   │   ├── graph/              # LangGraph graph definitions
│   │   │   ├── builder.py              # Compiles parent graph; owns PostgresSaver + PostgresStore
│   │   │   ├── parent_supervisor.py    # recover_state_node + supervisor_router (3-tier dispatch)
│   │   │   ├── router_logic.py         # gpt-4o tool-calling classifiers (fresh / workflow / resume / yes-no)
│   │   │   ├── faq_agents.py           # faq_kb_agent + general_faq_tavily_agent (siblings)
│   │   │   ├── prompts.py              # All system / clarification prompt templates
│   │   │   ├── state.py                # AppState (unified parent + subgraph), RA_STEP_* constants
│   │   │   ├── nodes/status_check.py   # status_agent
│   │   │   └── subgraphs/
│   │   │       └── request_access/
│   │   │           ├── graph.py        # Subgraph builder + intra-flow router; PARENT handoff for FAQ
│   │   │           ├── helpers.py      # Shared utilities, MCP search-app payload constants
│   │   │           ├── prompts.py      # Subgraph-specific prompt strings (incl. NARROW_AGENT_SYSTEM_TEMPLATE)
│   │   │           └── nodes/
│   │   │               ├── steps.py                  # Business steps (search → submit_request) + chip nodes (nav-only)
│   │   │               ├── narrow_search.py          # Conversational narrowing subagent (default path)
│   │   │               ├── navigation.py             # nav_intent dispatch + state invalidation
│   │   │               ├── mcp_prefetch.py           # Prefetches canonical facets from search MCP
│   │   │               └── extract_search_intent.py  # Normalizes free-text query, lifts study id
│   │   ├── mcp/                # MCP server registry + app folders
│   │   │   ├── registry.py             # Pure ASGI middleware mounts MCP servers at /mcp/{name}
│   │   │   ├── question-form-app-python/   # Form MCP App (Python server + Vite UI)
│   │   │   └── search-app/                 # Search MCP App (Python server + Vite UI)
│   │   ├── models/             # SQLAlchemy ORM models
│   │   ├── schema/             # Pydantic request/response schemas
│   │   └── service/            # Business logic services
│   │       ├── chat_service.py     # Graph invocation, SSE streaming, interrupt handling
│   │       ├── search_service.py   # ChromaDB vector search with metadata filters
│   │       ├── faq_service.py      # Tavily web search (used by both FAQ agents)
│   │       └── status_service.py   # In-memory request status tracking
│   ├── alembic/                # Database migrations
│   └── pyproject.toml          # Python dependencies (uv/hatch)
│
├── frontend/
│   ├── client/                 # Angular 21 SPA (standalone components)
│   │   └── src/app/
│   │       ├── features/chat/      # Chat UI (messages, input, interrupt rendering, SSE consumer)
│   │       ├── features/mcp-panel/ # Iframe host for MCP App resources
│   │       └── core/services/      # ChatService (SSE), McpService (MCP client)
│   └── server/                 # Express 5 BFF (proxies /api -> FastAPI, /mcp -> MCP servers)
│
├── question-form-app/          # Standalone MCP App prototype (TypeScript)
├── question-form-app-python/   # Standalone MCP App prototype (Python)
├── docs/                       # Architecture docs, design transcripts, Q&A
└── question-template.json      # JSON schema for the access request question form
```

## Key Technologies

| Layer | Technology | Version |
|-------|-----------|---------|
| Backend runtime | Python | >= 3.11 |
| Backend framework | FastAPI | >= 0.115 |
| AI orchestration | LangGraph | >= 0.4 |
| LLM provider | OpenAI gpt-4o (or Azure Kong, switchable) | via langchain-openai >= 0.3 |
| Vector store | ChromaDB | via langchain-chroma >= 0.2 |
| Graph persistence | PostgreSQL (checkpointer + store) | langgraph-checkpoint-postgres >= 2.0 |
| Web search | Tavily | via langchain-community |
| Streaming protocol | SSE (sse-starlette) + ag-ui-protocol | sse-starlette >= 2.2 |
| MCP protocol | MCP SDK | >= 1.9 |
| Frontend framework | Angular | 21 |
| BFF server | Express | 5 |
| Package manager (Python) | uv | latest |
| Package manager (JS) | npm | latest |

## Core Design Patterns

### 1. Supervisor Pattern (gpt-4o Tool-Calling Router)

`supervisor_router` in `parent_supervisor.py` is a 3-tier dispatcher:

1. **Structured UI resume** (`additional_kwargs.ra_ui` set) — bypass the LLM and route straight to the request-access subgraph. Button-click payloads are a typed contract; routing them through an LLM would be wasteful and non-deterministic.
2. **Active paused workflow** (`active_flow == "request_access"`) — calls `classify_workflow_text` (gpt-4o). Outcomes: `out_of_scope` / `clarify` / `faq` / `nav` (with `nav_target`) / `resume` / `side_text`.
3. **Fresh turn** — calls `classify_fresh_turn_text` (gpt-4o). Outcomes: `start_access` / `faq_kb` / `status_check` / `clarify` / `out_of_scope` / `direct`.

Confidence threshold: `0.9`. Below that, the supervisor emits a candidate-specific "Did you mean…?" message and stashes a `pending_clarification` dict; the next turn checks for a yes/no via `classify_yes_no` and dispatches without re-running the classifier.

### 2. Compiled Subgraph as a Node

`request_access_subgraph` is a compiled `StateGraph` attached as a single node on the parent graph. It owns its own intra-flow router (`route_request_access_turn`) and uses `Command(graph=Command.PARENT, goto=…)` to hand off back to the parent's FAQ agents when needed.

Checkpointing is configured **only on the parent** — `AsyncPostgresSaver` propagates to the subgraph automatically because it's attached as a compiled node, not invoked separately. Long-term cross-session memory uses `AsyncPostgresStore`, also owned by the parent.

### 3. Interrupt-Driven Human-in-the-Loop

Every user-facing step in the request-access subgraph uses LangGraph's `interrupt()` to pause, checkpoint state to PostgreSQL, and wait for the frontend to resume with `Command(resume=…)`. Interrupt payload types (see `state.py`):

- `facet_selection` — clickable chip buttons (legacy / nav-only)
- `product_selection` — product cards with checkboxes (allows search escape)
- `cart_review` — cart summary with action buttons
- `mcp_app` — opens an MCP App in a side panel
- `confirmation` — final submit/edit dialog
- `narrow_message` — plain assistant chat bubble (no chips, no buttons); the user replies via the normal chat input. `chat_service` detects the pending interrupt and wraps the typed text as `Command(resume={"action": "user_message", "text": …})`.

All payloads carry `step` + `prompt_id` so the frontend can correlate resume responses. `prompt_id` is **required** (validated client-side via `INTERRUPT_REQUIRED_FIELDS`) and is the basis for the stale-interrupt UX described below.

### 3a. Stale-Interrupt UX (`prompt_id` correlation)

When the user types past an interactive interrupt instead of clicking on its widget — e.g. asks an FAQ while a `product_selection` bubble is on screen, or types "change the anonymization" while an `mcp_app` panel is open — the conversation moves on but the historical bubble would otherwise still expose stale, clickable widgets. The frontend defends against this:

- `ChatService.currentInterrupt` is cleared on every resume submit and replaced when a new interrupt arrives.
- `ChatComponent` exposes `activePromptId = currentInterrupt()?.interrupt_value?.prompt_id` and pipes it into every `<app-message>`.
- `MessageComponent` derives `isStale = msg.interrupt.prompt_id !== activePromptId`. When stale **and** the original interrupt carried a widget (anything except `narrow_message`), the bubble's prompt text and the widget are both replaced with a single `User Skipped <Action>` notice in dashed-badge styling. The bubble shape is preserved so the transcript still reads naturally.
- `narrow_message` bubbles are exempt — they are plain text, so there is nothing to skip past.
- A separate `Completed` (green) badge still flips on locally when the user actually clicks a button on the bubble, keeping clicked-and-acted bubbles visually distinct from skipped ones.

The contract is one-way: the backend issues a fresh `prompt_id` for every `interrupt()` call (UUIDs from `_hitl_step` and `narrow_search.py`, plus the stable `"mcp_search"` id for the search panel) and the frontend uses id equality alone to decide whether a widget is still actionable.

### 4. Conversational Narrowing Subagent (`narrow_search`)

The default request-access path no longer goes through the chip-based `choose_domain` + `choose_anonymization` nodes. Instead, after `mcp_prefetch_facets` runs once, control jumps to the `narrow_search` subagent (`subgraphs/request_access/nodes/narrow_search.py`), a hand-rolled ReAct-style loop with two tools:

- `ask_user(message)` — emits a `narrow_message` interrupt and pauses for the user's typed reply.
- `commit_narrow(search_text, domain, anonymization, study_id)` — finalizes the filters and hands off to `search_products`.

The system prompt (`NARROW_AGENT_SYSTEM_TEMPLATE` in `prompts.py`) is injected with the canonical facet ids from `mcp_facet_cache` and a summary of what the supervisor already extracted. The agent batches the optional facets into one follow-up question once a topic is in hand, maps paraphrases to canonical ids silently, and is instructed to confirm bare numeric IDs that don't match the `dp-NNN` study-id shape (lowercase `dp-` prefix + digits, e.g. `dp-501`) before treating them as a study id. A defensive cap of 4 `ask_user` round-trips force-commits if the LLM misbehaves; intent-noise phrases like "request access" or "data products" are filtered out of both the seed and the `commit_narrow` fallback so the agent never confuses them for a real search topic.

Each call to `narrow_search` performs **at most one `interrupt()`** and routes back to itself via `Command(goto="narrow_search")` after the resume. This keeps each LangGraph node execution to a single interrupt boundary and avoids the multi-`interrupt()`-in-one-node rerun trap (where non-deterministic LLM calls would invalidate cached interrupt correlation).

Chip nodes (`choose_domain` / `choose_anonymization`) remain registered and reachable via explicit `nav_intent` — they're now an escape hatch rather than the default path.

### 5. Universal "Back to Narrow" Escape Hatch

Any downstream step can route back through `handle_navigation` → `invalidate_downstream_state` → `goto_target_step` to clear stale state and restart at any earlier step. The user can refine filters, change selections, or add more products at any point.

### 6. MCP Apps Integration

MCP servers are mounted via a **pure ASGI middleware** (`McpRoutingMiddleware`), not `BaseHTTPMiddleware` — this preserves SSE/streaming with zero buffering and avoids Starlette trailing-slash redirects that break MCP clients. Each MCP App has:

- A `server.py` exposing `create_server()` returning an MCP `Server` instance
- An `mcp-app.html` built by Vite from `src/mcp-app.ts`
- Tools called by graph nodes (e.g. `mcp_prefetch_facets` calls the search-app for canonical chip ids/labels)
- UI resources rendered in the frontend MCP panel

## Shared State (`graph/state.py:AppState`)

A single `TypedDict` is shared between parent and subgraph (no separate `AccessRequestState`). Notable fields:

- **Conversation:** `messages` (annotated with `operator.add`), `thread_id`, `user_id`
- **Orchestration:** `active_flow`, `mode`, `active_intent`, `supervisor_decision`, `paused_workflow_summary`, `pending_clarification`
- **Workflow progress:** `current_step`, `selected_domains`, `selected_anonymization`, `product_type_filter`, `product_search_results`, `selected_products`, `cart_snapshot`, `generated_form_schema`, `form_answers`
- **Routing aids:** `nav_intent`, `invalidated_from_step`, `last_resume_value`, `last_workflow_node`, `ra_search_query`, `ra_study_id`
- **MCP cache:** `mcp_facet_cache` (canonical chips fetched once per subgraph entry)
- **Narrowing subagent:** `narrow_state` — `{messages, turns, pending_tc_id}`; owned by `narrow_search`, cleared on commit.

Step constants live in the same module: `RA_STEP_NARROW_SEARCH` (default first step), `RA_STEP_CHOOSE_DOMAIN`, `RA_STEP_CHOOSE_ANONYMIZATION` (chip nav targets), `RA_STEP_SEARCH_PRODUCTS`, `RA_STEP_CHOOSE_PRODUCTS`, `RA_STEP_SHOW_CART`, `RA_STEP_GENERATE_FORM`, `RA_STEP_FILL_FORM`, `RA_STEP_SUBMIT`, with a `RA_STEP_TO_NODE` mapping. `RA_STEPS_ORDER` lists the linear default story (narrow → search → pick → review → form → submit); the chip nodes are intentionally NOT in that order.

## Environment Variables

Required in `backend/.env`:

```
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://user:pass@localhost:5432/dbname
TAVILY_API_KEY=tvly-...
DB_SCHEMA=public                 # explicit, no silent fallback
```

LLM provider is switchable (OpenAI / Azure Kong) via `app.core.llm.get_chat_llm` — see `.env.example`.

## Development Setup

### Backend

```bash
cd backend
uv sync                    # Install Python dependencies
uv run uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend/client
npm install
npm run build              # Build Angular app

cd ../server
npm install
npm run dev                # Start BFF on port 4200
```

### MCP App UI builds

```bash
cd backend/app/mcp/question-form-app-python
npm install && npm run build    # Builds mcp-app.html via Vite

cd ../search-app
npm install && npm run build
```

### Database

PostgreSQL must be running for both the LangGraph checkpointer and store. Alembic handles schema migrations:

```bash
cd backend
uv run alembic upgrade head
```

The schema must exist before migrations — `scripts/ensure_schema.py` requires `DB_SCHEMA` to be set explicitly (no silent fallback).

## Code Conventions

- **Python:** Type hints everywhere. `from __future__ import annotations` at the top of every module. Pydantic for validation, `TypedDict` for graph state.
- **TypeScript / Angular:** Standalone components (no NgModules). Services use RxJS observables. SSE consumed via the native `EventSource` in `ChatService`.
- **Graph nodes:** Each node is a pure function `(state) -> dict | Command`. Never mutate state directly — return updates. Prefer `Command(update=…, goto=…)` over plain dict returns when routing.
- **Routing:** All free-text intent goes through `router_logic.py` classifiers (gpt-4o tool-calling). Structured UI payloads dispatch deterministically — never route them through an LLM.
- **Logging:** `logging.getLogger(__name__)` in Python. Log at `info` for routing decisions, `debug` for data payloads.

## Testing Guidance

- Graph nodes can be tested in isolation by constructing an `AppState` dict and calling the node function directly.
- The `ChatService` can be tested by mocking the compiled graph's `astream` / `ainvoke` method.
- MCP Apps can be tested by calling their `create_server()` function and sending MCP protocol messages.
- Frontend components can be tested with Angular's TestBed.
- Backend tests live in `backend/tests/` (`conftest.py` provides shared fixtures).

## Common Tasks

### Adding a new sibling agent under the supervisor

1. Implement the agent in `graph/` (e.g. `graph/nodes/my_agent.py`) returning a state dict.
2. Add a tool definition in `router_logic.py` so `classify_fresh_turn_text` (and/or `classify_workflow_text`) can pick it.
3. Add the matching `kind` branch in `supervisor_router` (`parent_supervisor.py`) and, if needed, in `_dispatch_from_clarification`.
4. Wire it into `builder.py` with `add_node` + a terminal `add_edge(node, END)`.

### Adding a new step to the request-access subgraph

1. Add the step constant to `state.py` (`RA_STEP_*`, `RA_STEPS_ORDER`, `RA_STEP_TO_NODE`) and any new `AppState` fields.
2. Implement the node in `subgraphs/request_access/nodes/steps.py` (or a new file in `nodes/`).
3. Register it in `build_request_access_subgraph` in `subgraphs/request_access/graph.py`, including the `END` fall-through edge.
4. Update `_dispatch_fresh` and `_apply_structured_answer` if the step accepts structured UI payloads.

### Adding a new MCP App

1. Create a folder under `backend/app/mcp/{app-name}/`.
2. Add `server.py` exposing `create_server()` that returns an MCP `Server` instance.
3. Add `src/mcp-app.ts` + `vite.config.ts` (or a static `mcp-app.html`).
4. Register the app in `MCP_APPS` in `registry.py`.
5. If a graph node needs to call a tool on the new server, add a helper alongside `mcp_prefetch.py`.
