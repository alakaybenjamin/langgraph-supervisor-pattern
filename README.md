# LangGraph Supervisor Pattern

A full-stack reference implementation of the **LangGraph Supervisor Pattern** — an AI orchestration architecture where a central supervisor LLM classifies user intent via tool-calling and routes to specialized sub-flows, with interrupt-driven human-in-the-loop interactions and embedded MCP (Model Context Protocol) Apps.

## What This Demonstrates

- **Supervisor Pattern**: An LLM-powered router that uses tool-calling to classify intent and dispatch to the correct subgraph — no hand-written classifiers or keyword matching.
- **Interrupt-Driven HITL**: Every user-facing step pauses the graph with `interrupt()`, checkpoints state to PostgreSQL, and resumes when the frontend sends the user's response via `Command(resume=...)`.
- **MCP Apps Integration**: Rich interactive UI panels (search, forms) served as MCP resources and mounted directly on the FastAPI backend.
- **Multi-Step Subgraphs**: A 7-node request access workflow with conditional routing, cart management, form filling, and confirmation — all orchestrated by LangGraph.

## Architecture

```
Angular 19 SPA ──► Express BFF ──► FastAPI Backend
                                        │
                                  LangGraph Supervisor (gpt-4o)
                                 ┌───────┼───────────┐
                                 ▼       ▼           ▼
                              FAQ     Status    Request Access
                            (Tavily)  (memory)     Subgraph
                                                     │
                                              ┌──────┼──────┐
                                              ▼      ▼      ▼
                                          Narrow  Search  Forms
                                          (chips) (MCP)   (MCP)
```

The request access subgraph contains 7 interrupt-driven nodes:

1. **Narrow** — Domain and type selection via chip buttons
2. **Show Results** — Vector search results displayed as product cards
3. **Search App** — Full search MCP App in a side panel
4. **Review Cart** — Selected products summary
5. **Fill Form** — Question form MCP App (loops per product)
6. **Confirm** — Final summary with submit/edit/add-more
7. **Submit** — Generates a request ID

See [`docs/graph-architecture.md`](docs/graph-architecture.md) for detailed Mermaid diagrams.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, LangGraph, LangChain |
| LLM | OpenAI gpt-4o **or** Azure OpenAI via Kong Gateway (switchable) |
| Vector Store | ChromaDB (in-process) |
| Graph Persistence | PostgreSQL (LangGraph checkpointer) |
| MCP | MCP SDK (Streamable HTTP) |
| Frontend | Angular 19, TypeScript |
| BFF | Express 5, http-proxy-middleware |

## Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL (running locally or via Docker)
- OpenAI API key **or** Kong Gateway credentials (client ID + secret)
- Tavily API key (for FAQ search)

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/alakaybenjamin/langgraph-supervisor-pattern.git
cd langgraph-supervisor-pattern
cp .env.example backend/.env
```

Edit `backend/.env` and fill in the values. See [Configuration](#configuration) below for details.

### 2. Database setup

The project uses **two** PostgreSQL users with strict separation:

| User | Purpose | Set in `.env` as |
|------|---------|-----------------|
| **Admin** | DDL only — Alembic migrations, schema creation, checkpointer table setup, privilege grants. Never deployed to production. | `DATABASE_ADMIN_USER` / `DATABASE_ADMIN_PASSWORD` |
| **RW** | Runtime only — used exclusively by the running application. | `DATABASE_RW_USER` / `DATABASE_RW_PASSWORD` |

Run the admin scripts **once** (in order) before starting the app:

```bash
cd backend
export $(grep -v '^#' .env | xargs)

# 1. Create the target schema (skip if using "public")
python scripts/ensure_schema.py

# 2. Run Alembic migrations (application tables)
uv run alembic upgrade head

# 3. Create LangGraph checkpointer tables
python scripts/setup_checkpointer.py

# 4. Grant RW privileges to the runtime user
python scripts/grant_rw_privileges.py
```

### 3. Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

### 4. Frontend

```bash
# Build Angular client
cd frontend/client
npm install
npm run build

# Start BFF server
cd ../server
npm install
npm run dev
```

The app will be available at `http://localhost:4200`.

### 5. MCP App UIs (if modifying)

```bash
cd backend/app/mcp/question-form-app-python
npm install && npm run build

cd ../search-app
npm install && npm run build
```

## Configuration

All configuration is via environment variables in `backend/.env`. Copy `.env.example` as a starting point.

### LLM Provider

Set `LLM_PROVIDER` to switch between providers — no code changes needed:

| Value | Provider | Required variables |
|-------|----------|--------------------|
| `openai` (default) | Direct OpenAI API | `OPENAI_API_KEY` |
| `azure_kong` | Azure OpenAI via Kong Gateway | `KONG_CLIENT_ID`, `KONG_CLIENT_SECRET`, `KONG_BASE_URL`, `FEDERATION_URL` |

### PostgreSQL

Database connection is configured via atomic environment variables (not a single URL):

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_HOSTNAME` | PostgreSQL host | `localhost` |
| `DATABASE_PORT` | PostgreSQL port | `5432` |
| `DATABASE_NAME` | Database name | `postgres` |
| `DATABASE_RW_USER` | Runtime user (app) | — |
| `DATABASE_RW_PASSWORD` | Runtime password | — |
| `DATABASE_ADMIN_USER` | Admin user (DDL scripts + Alembic) | — |
| `DATABASE_ADMIN_PASSWORD` | Admin password | — |
| `DB_SCHEMA` | Target schema for all tables | `public` |

## Project Structure

```
backend/                    # FastAPI + LangGraph
  app/
    core/                   # Config (pydantic-settings), LLM factory, Kong auth
    graph/                  # LangGraph supervisor, nodes, subgraphs
    mcp/                    # MCP server registry + app folders
    service/                # Business logic (search, FAQ, status)
    api/                    # REST endpoints
    db/                     # SQLAlchemy async session, Alembic integration
  scripts/                  # Admin DB scripts (schema, checkpointer, grants)
  alembic/                  # Database migrations
frontend/
  client/                   # Angular 19 SPA
  server/                   # Express BFF (proxy layer)
docs/                       # Architecture diagrams and design docs
```

## Key Files

| File | Purpose |
|------|---------|
| `backend/app/graph/supervisor.py` | Supervisor node — LLM intent classification |
| `backend/app/graph/builder.py` | Parent graph compilation with checkpointer |
| `backend/app/graph/subgraphs/request_access/graph.py` | Request access subgraph with 7 nodes |
| `backend/app/core/config.py` | Pydantic settings with strict admin/RW URL separation |
| `backend/app/core/llm.py` | LLM factory — `get_chat_llm()` / `get_embeddings()` |
| `backend/app/core/kong_auth.py` | Kong Gateway OAuth2 token provider |
| `backend/app/mcp/registry.py` | Auto-discovers and mounts MCP servers |
| `backend/app/service/chat_service.py` | Graph invocation and interrupt handling |
| `backend/scripts/ensure_schema.py` | Creates target schema (admin only) |
| `backend/scripts/setup_checkpointer.py` | Creates LangGraph checkpoint tables (admin only) |
| `backend/scripts/grant_rw_privileges.py` | Grants RW user access to all schema objects (admin only) |
| `frontend/server/src/index.ts` | BFF proxy configuration |

## License

MIT
