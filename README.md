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
| LLM | OpenAI gpt-4o |
| Vector Store | ChromaDB (in-process) |
| Graph Persistence | PostgreSQL (LangGraph checkpointer) |
| MCP | MCP SDK (Streamable HTTP) |
| Frontend | Angular 19, TypeScript |
| BFF | Express 5, http-proxy-middleware |

## Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL (running locally or via Docker)
- OpenAI API key
- Tavily API key (for FAQ search)

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/alakaybenjamin/langgraph-supervisor-pattern.git
cd langgraph-supervisor-pattern
```

Create `backend/.env`:
```env
OPENAI_API_KEY=sk-your-key-here
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
TAVILY_API_KEY=tvly-your-key-here
```

### 2. Backend

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

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

### 4. MCP App UIs (if modifying)

```bash
cd backend/app/mcp/question-form-app-python
npm install && npm run build

cd ../search-app
npm install && npm run build
```

## Project Structure

```
backend/                    # FastAPI + LangGraph
  app/
    graph/                  # LangGraph supervisor, nodes, subgraphs
    mcp/                    # MCP server registry + app folders
    service/                # Business logic (search, FAQ, status)
    api/                    # REST endpoints
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
| `backend/app/mcp/registry.py` | Auto-discovers and mounts MCP servers |
| `backend/app/service/chat_service.py` | Graph invocation and interrupt handling |
| `frontend/server/src/index.ts` | BFF proxy configuration |

## License

MIT
