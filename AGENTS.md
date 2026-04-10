# AGENTS.md — LangGraph Supervisor Pattern

This file provides context for AI agents working on this codebase.

## Project Overview

A **Data Governance Chat Application** that demonstrates the **LangGraph Supervisor Pattern** — an AI orchestration architecture where a central supervisor LLM routes user intent to specialized sub-flows (subgraphs) using tool-calling. The system integrates interactive MCP (Model Context Protocol) Apps for rich UI within the conversation flow.

### Architecture at a Glance

```
User <-> Angular Frontend <-> Express BFF <-> FastAPI Backend
                                                  |
                                           LangGraph Supervisor
                                          /        |          \
                                   FAQ Node   Status Node   Request Access Subgraph
                                  (Tavily)   (in-memory)    (7 interrupt-driven nodes)
                                                              |
                                                     MCP Apps (Search, Forms)
```

## Directory Structure

```
├── backend/                    # Python FastAPI + LangGraph backend
│   ├── app/
│   │   ├── main.py             # FastAPI entry point, lifespan events
│   │   ├── api/routes/         # REST endpoints (chat, health)
│   │   ├── core/               # Config (pydantic-settings), logging
│   │   ├── db/                 # SQLAlchemy async session, Alembic integration
│   │   ├── graph/              # LangGraph graph definitions
│   │   │   ├── builder.py      # Compiles parent graph with PostgresSaver checkpointer
│   │   │   ├── supervisor.py   # Supervisor node — LLM intent classifier via tool calls
│   │   │   ├── state.py        # TypedDict state schemas (SupervisorState, AccessRequestState)
│   │   │   ├── nodes/          # Top-level nodes (faq, status_check)
│   │   │   └── subgraphs/
│   │   │       └── request_access/
│   │   │           ├── graph.py    # Request access subgraph builder with conditional routing
│   │   │           └── nodes/      # 7 nodes: narrow, show_results, search_app, review_cart,
│   │   │                           #          fill_form, confirm, submit
│   │   ├── mcp/                # MCP server registry + app folders
│   │   │   ├── registry.py     # Auto-discovers and mounts MCP servers on FastAPI
│   │   │   ├── question-form-app-python/   # Question form MCP App (Python server + Vite UI)
│   │   │   └── search-app/                 # Search MCP App (TypeScript server + Vite UI)
│   │   ├── models/             # SQLAlchemy ORM models
│   │   ├── schema/             # Pydantic request/response schemas
│   │   └── service/            # Business logic services
│   │       ├── chat_service.py     # Graph invocation + interrupt handling
│   │       ├── search_service.py   # ChromaDB vector search with metadata filters
│   │       ├── faq_service.py      # Tavily web search for FAQ
│   │       └── status_service.py   # In-memory request status tracking
│   ├── alembic/                # Database migrations
│   └── pyproject.toml          # Python dependencies (uv/hatch)
│
├── frontend/
│   ├── client/                 # Angular 19 SPA
│   │   └── src/app/
│   │       ├── features/chat/  # Chat UI components (messages, input, interrupt rendering)
│   │       ├── features/mcp-panel/  # MCP App panel (iframe host for MCP Apps)
│   │       └── core/services/  # ChatService (HTTP), McpService (MCP client)
│   └── server/                 # Express BFF (proxies /api -> FastAPI, /mcp -> MCP servers)
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
| LLM provider | OpenAI (gpt-4o) | via langchain-openai >= 0.3 |
| Vector store | ChromaDB | via langchain-chroma >= 0.2 |
| Graph persistence | PostgreSQL | via langgraph-checkpoint-postgres >= 2.0 |
| MCP protocol | MCP SDK | >= 1.9 |
| Frontend framework | Angular | 19 |
| BFF server | Express | 5 |
| Package manager (Python) | uv | latest |
| Package manager (JS) | npm | latest |

## Core Design Patterns

### 1. Supervisor Pattern (Tool-Calling Router)
The supervisor node (`backend/app/graph/supervisor.py`) uses an LLM with bound tools to classify user intent. Each tool maps to a subgraph or node:
- `start_access_request` -> `request_access` subgraph
- `answer_question` -> `faq` node
- `check_request_status` -> `status_check` node

The supervisor uses `Command(goto=...)` to route to the chosen node. If no tool is called, it responds directly.

### 2. Interrupt-Driven Human-in-the-Loop
Every user-facing step in the request access subgraph uses LangGraph's `interrupt()` to pause, checkpoint state to PostgreSQL, and wait for the frontend to resume with `Command(resume=...)`. Interrupt types:
- `facet_selection` — clickable chip buttons
- `product_selection` — product cards with checkboxes
- `cart_review` — cart summary with action buttons
- `mcp_app` — opens an MCP App in a side panel
- `confirmation` — submit/edit/add-more summary

### 3. MCP Apps Integration
MCP servers are mounted directly on the FastAPI app via ASGI middleware (`registry.py`). Each MCP App has:
- A `server.py` defining MCP tools and UI resources
- An `mcp-app.html` compiled by Vite from TypeScript source
- Tools callable by the graph nodes, resources renderable in the frontend panel

### 4. Universal "Back to Narrow" Escape Hatch
Any downstream node can route back to the `narrow` node by clearing facet state, enabling users to refine filters, change selections, or add more products at any point.

## Environment Variables

Required in `backend/.env`:
```
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://user:pass@localhost:5432/dbname
TAVILY_API_KEY=tvly-...
```

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
PostgreSQL must be running for the LangGraph checkpointer. Alembic handles schema migrations:
```bash
cd backend
uv run alembic upgrade head
```

## Code Conventions

- **Python**: Type hints everywhere. Use `from __future__ import annotations` at the top of every module. Pydantic for validation, TypedDict for graph state.
- **TypeScript/Angular**: Standalone components (no NgModules). Services use RxJS observables.
- **Graph nodes**: Each node is a pure function `(state) -> dict | Command`. Never mutate state directly — return updates.
- **Logging**: Use `logging.getLogger(__name__)` in Python. Log at `info` for routing decisions, `debug` for data payloads.

## Testing Guidance

- Graph nodes can be tested in isolation by constructing a state dict and calling the node function directly.
- The `ChatService` can be tested by mocking the compiled graph's `ainvoke` method.
- MCP Apps can be tested by calling their `create_server()` function and sending MCP protocol messages.
- Frontend components can be tested with Angular's TestBed.

## Common Tasks

### Adding a new intent to the supervisor
1. Add a new `@tool` function in `supervisor.py`
2. Add it to `SUPERVISOR_TOOLS`
3. Add a new `elif` branch in `supervisor_node` with a `Command(goto=...)`
4. Create the target node in `graph/nodes/`
5. Wire it into `builder.py` with `add_node` and `add_edge`

### Adding a new node to the request access subgraph
1. Create the node function in `graph/subgraphs/request_access/nodes/`
2. Add any new state fields to `AccessRequestState` in `state.py`
3. Wire it into `graph/subgraphs/request_access/graph.py`
4. Add conditional routing functions as needed

### Adding a new MCP App
1. Create a folder under `backend/app/mcp/{app-name}/`
2. Add `server.py` with `create_server()` that returns an MCP `Server` instance
3. Add `mcp-app.html` (or `src/mcp-app.ts` + Vite build)
4. Register in `MCP_APPS` list in `registry.py`
