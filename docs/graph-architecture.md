# Data Governance Chat — Graph Architecture

## Full System Diagram

```mermaid
flowchart TB
    START((START))
    END_NODE((END))

    START --> SUPERVISOR

    subgraph PARENT["Parent Graph - Supervisor Router"]
        direction TB
        SUPERVISOR["supervisor_node\nLLM: gpt-4o\nRoutes user intent via tool calls"]

        SUPERVISOR -->|"tool: start_access_request"| CMD_RA["Command: request_access"]
        SUPERVISOR -->|"tool: answer_question"| CMD_FAQ["Command: faq"]
        SUPERVISOR -->|"tool: check_request_status"| CMD_STATUS["Command: status_check"]
        SUPERVISOR -->|"no tool call"| END_NODE

        subgraph FAQ_FLOW["FAQ Flow"]
            FAQ_NODE["faq_node\nSearch + Synthesize via LLM"]
            FAQ_SVC[("FaqService\nChromaDB")]
            FAQ_NODE -.->|"vector search"| FAQ_SVC
        end

        CMD_FAQ --> FAQ_NODE
        FAQ_NODE -->|"returns answer"| SUPERVISOR

        subgraph STATUS_FLOW["Status Check Flow"]
            STATUS_NODE["status_check_node\nLookup by request ID"]
            STATUS_SVC[("StatusService\nIn-memory store")]
            STATUS_NODE -.->|"get_status"| STATUS_SVC
        end

        CMD_STATUS --> STATUS_NODE
        STATUS_NODE -->|"returns status"| SUPERVISOR
    end

    CMD_RA --> RA_START

    subgraph REQUEST_ACCESS["Request Access Subgraph"]
        direction TB

        RA_START((S))
        RA_END((E))

        RA_START --> EXTRACT

        EXTRACT["extract_search_intent\nNormalises free-text query\nLifts study_id (dp-NNN)"]
        PREFETCH["mcp_prefetch_facets\nFetches canonical chip ids\nfrom search MCP (cached once)"]
        EXTRACT --> PREFETCH
        PREFETCH --> NARROW

        NARROW["narrow_search\nConversational subagent\nReAct loop: ask_user / commit_narrow\ninterrupt: narrow_message"]
        INT_NARROW>"PAUSE: Plain assistant chat bubble\nUser replies via normal chat input\n(wrapped as Command(resume))"]
        NARROW --- INT_NARROW

        CHIP_DOMAIN["choose_domain (nav-only)\ninterrupt: facet_selection"]
        CHIP_ANON["choose_anonymization (nav-only)\ninterrupt: facet_selection"]
        INT_CHIP1>"PAUSE: Domain chips\nReachable only via nav_intent"]
        INT_CHIP2>"PAUSE: Anonymization chips\nReachable only via nav_intent"]
        CHIP_DOMAIN --- INT_CHIP1
        CHIP_ANON --- INT_CHIP2

        SHOW["show_results_node\nSearch ChromaDB + display cards\ninterrupt: product_selection"]
        SEARCH_SVC[("SearchService\nChromaDB")]
        SHOW -.->|"search_with_filters"| SEARCH_SVC
        INT_SHOW>"PAUSE: Product cards\n+ Open Search Panel\n+ Refine Filters"]
        SHOW --- INT_SHOW

        SEARCH_APP["search_app_node\ninterrupt: mcp_app"]
        MCP_SEARCH["SEARCH MCP APP\nui://search-app\n/mcp/search-app\nTool: search-data-products"]
        SEARCH_APP --- MCP_SEARCH

        REVIEW["review_cart_node\nDisplay selected products\ninterrupt: cart_review"]
        INT_REVIEW>"PAUSE: Cart summary\n+ Fill Forms / Add More / Change"]
        REVIEW --- INT_REVIEW

        FILL["fill_form_node\nLoop per product\ninterrupt: mcp_app"]
        MCP_FORM["QUESTION FORM MCP APP\nui://question-form\n/mcp/question-form\nTool: open-question-form"]
        FILL --- MCP_FORM

        CONFIRM["confirm_node\nShow full summary\ninterrupt: confirmation"]
        INT_CONFIRM>"PAUSE: Summary\n+ Submit / Edit / Add More"]
        CONFIRM --- INT_CONFIRM

        SUBMIT["submit_node\nGenerate REQ-ID"]

        NARROW -->|"commit_narrow"| SHOW
        SHOW -->|"products selected"| REVIEW
        REVIEW -->|"fill_forms"| FILL
        FILL -->|"all forms done"| CONFIRM
        CONFIRM -->|"confirm"| SUBMIT
        SUBMIT --> RA_END

        NARROW -->|"ask_user (self-loop\nvia Command(goto))"| NARROW
        SHOW -->|"open_search"| SEARCH_APP
        SHOW -->|"refine_filters"| NARROW
        SEARCH_APP -->|"products selected"| REVIEW
        REVIEW -->|"add_more / change"| NARROW
        FILL -->|"next product"| FILL
        FILL -->|"add_more"| NARROW
        CONFIRM -->|"edit"| FILL
        CONFIRM -->|"add_more"| NARROW

        CHIP_DOMAIN -->|"chip clicked"| NARROW
        CHIP_ANON -->|"chip clicked"| NARROW
    end

    RA_END --> END_NODE

    style START fill:#1e293b,color:#fff,stroke:#0f172a
    style END_NODE fill:#1e293b,color:#fff,stroke:#0f172a
    style RA_START fill:#1e293b,color:#fff,stroke:#0f172a
    style RA_END fill:#1e293b,color:#fff,stroke:#0f172a

    style SUPERVISOR fill:#7c3aed,color:#fff,stroke:#5b21b6,stroke-width:2px
    style CMD_RA fill:#e2e8f0,stroke:#94a3b8
    style CMD_FAQ fill:#e2e8f0,stroke:#94a3b8
    style CMD_STATUS fill:#e2e8f0,stroke:#94a3b8

    style FAQ_NODE fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style FAQ_SVC fill:#6366f1,color:#fff,stroke:#4f46e5
    style STATUS_NODE fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style STATUS_SVC fill:#6366f1,color:#fff,stroke:#4f46e5

    style EXTRACT fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style PREFETCH fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style NARROW fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style SHOW fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style SEARCH_APP fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style REVIEW fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style FILL fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style CONFIRM fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style SUBMIT fill:#ef4444,color:#fff,stroke:#dc2626,stroke-width:2px

    style CHIP_DOMAIN fill:#94a3b8,color:#fff,stroke:#64748b,stroke-dasharray:5 5
    style CHIP_ANON fill:#94a3b8,color:#fff,stroke:#64748b,stroke-dasharray:5 5

    style INT_NARROW fill:#fef3c7,color:#000,stroke:#f59e0b,stroke-width:2px
    style INT_CHIP1 fill:#fef3c7,color:#000,stroke:#f59e0b,stroke-width:2px
    style INT_CHIP2 fill:#fef3c7,color:#000,stroke:#f59e0b,stroke-width:2px
    style INT_SHOW fill:#fef3c7,color:#000,stroke:#f59e0b,stroke-width:2px
    style INT_REVIEW fill:#fef3c7,color:#000,stroke:#f59e0b,stroke-width:2px
    style INT_CONFIRM fill:#fef3c7,color:#000,stroke:#f59e0b,stroke-width:2px

    style MCP_SEARCH fill:#10b981,color:#fff,stroke:#059669,stroke-width:2px
    style MCP_FORM fill:#10b981,color:#fff,stroke:#059669,stroke-width:2px

    style SEARCH_SVC fill:#6366f1,color:#fff,stroke:#4f46e5
```

## Interrupt Types at Each Node

Every `interrupt()` call pauses the graph and sends a payload to the frontend.
The frontend renders appropriate UI and resumes the graph with user input.

```mermaid
flowchart LR
    subgraph Interrupts["Interrupt Types to Frontend Rendering"]
        direction TB

        NM["narrow_message"] -->|"renders"| BUBBLE["Plain assistant chat bubble\nuser replies via normal input\n(default narrowing path)"]

        FS["facet_selection"] -->|"renders"| CHIPS["Clickable chip buttons\nin chat message\n(nav-only escape hatch)"]

        PS["product_selection"] -->|"renders"| CARDS["Product cards with\ncheckboxes + action buttons\nRefine / Search / Add"]

        CR["cart_review"] -->|"renders"| CART["Cart summary with\naction buttons\nFill Forms / Add More / Change"]

        MA["mcp_app\nquestion-form"] -->|"opens"| FORM["Question Form\nMCP App in\nright panel"]

        MA2["mcp_app\nsearch-app"] -->|"opens"| SEARCH["Search Data Products\nMCP App in\nright panel"]

        CF["confirmation"] -->|"renders"| SUMMARY["Summary with\naction buttons\nSubmit / Edit / Add More"]
    end

    style NM fill:#f59e0b,color:#000,stroke:#d97706
    style FS fill:#f59e0b,color:#000,stroke:#d97706
    style PS fill:#f59e0b,color:#000,stroke:#d97706
    style CR fill:#f59e0b,color:#000,stroke:#d97706
    style MA fill:#f59e0b,color:#000,stroke:#d97706
    style MA2 fill:#f59e0b,color:#000,stroke:#d97706
    style CF fill:#f59e0b,color:#000,stroke:#d97706

    style BUBBLE fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style CHIPS fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style CARDS fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style CART fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style SUMMARY fill:#3b82f6,color:#fff,stroke:#1d4ed8

    style FORM fill:#10b981,color:#fff,stroke:#059669
    style SEARCH fill:#10b981,color:#fff,stroke:#059669
```

Every interrupt payload also carries a `prompt_id` (UUID per `interrupt()` call, plus the stable `"mcp_search"` id for the search panel). The frontend stores the active id in `ChatService.currentInterrupt` and passes it down to every `<app-message>` so historical bubbles whose `prompt_id` no longer matches render as **superseded** — their widget is hidden and the bubble's content is replaced with a single `User Skipped <Action>` notice. This keeps the user from clicking on stale chips/buttons after the conversation has moved on.

## Intent Switching — How Users Can Change Direction

The system supports mid-flow navigation at every step. Users can escape to earlier stages or switch intent entirely.

```mermaid
stateDiagram-v2
    state "Supervisor" as SUP
    state "Request Access Subgraph" as RA {
        state "extract_search_intent" as EX
        state "mcp_prefetch_facets" as PF
        state "narrow_search (default)" as N
        state "choose_domain (nav-only chips)" as CD
        state "choose_anonymization (nav-only chips)" as CA
        state "show_results" as SR
        state "search_app" as SA
        state "review_cart" as RC
        state "fill_form" as FF
        state "confirm" as C
        state "submit" as S

        [*] --> EX
        EX --> PF
        PF --> N

        N --> N : ask_user (Command(goto=narrow_search))
        N --> SR : commit_narrow

        CD --> N : chip clicked
        CA --> N : chip clicked

        SR --> SA : open_search
        SR --> N : refine_filters
        SR --> RC : products selected
        SR --> FF : direct select

        SA --> RC : products from MCP App

        RC --> FF : fill_forms
        RC --> N : add_more
        RC --> N : change_selection

        FF --> FF : next product in loop
        FF --> N : add_more
        FF --> C : all forms done

        C --> S : confirm
        C --> FF : edit
        C --> N : add_more

        S --> [*]
    }
    state "FAQ" as FAQ
    state "Status Check" as SC

    [*] --> SUP
    SUP --> RA : start_access_request
    SUP --> FAQ : answer_question
    SUP --> SC : check_request_status
    SUP --> [*] : clarification

    FAQ --> SUP
    SC --> SUP
    RA --> [*]
```

`choose_domain` and `choose_anonymization` are reachable **only** via `nav_intent` (the user typing something like "change the anonymization") — they are not on the default story arc. The `narrow_search` self-loop is implemented as a `Command(goto="narrow_search")` after each `interrupt()` so each node execution stays at exactly one interrupt boundary, avoiding the multi-`interrupt()`-in-one-node rerun trap.

## Services and External Dependencies

```mermaid
flowchart LR
    subgraph LLMs
        GPT["OpenAI gpt-4o (or Azure Kong)"]
    end

    subgraph Services
        SS["SearchService"]
        FS["FaqService"]
        STS["StatusService"]
    end

    subgraph DataStores
        CHROMA_PRODUCTS[("ChromaDB\nData Products\n10 products")]
        CHROMA_FAQ[("ChromaDB\nFAQ Knowledge")]
        INMEM[("In-Memory\nRequest Status")]
    end

    subgraph MCP_Servers["MCP Servers on FastAPI"]
        QF["/mcp/question-form\nTool: open-question-form\nResource: ui://question-form"]
        SA["/mcp/search-app\nTool: search-data-products\nResource: ui://search-app"]
    end

    subgraph Persistence
        PG[("PostgreSQL\nLangGraph Checkpointer")]
    end

    SS -->|"vector search"| CHROMA_PRODUCTS
    FS -->|"vector search"| CHROMA_FAQ
    STS -->|"read/write"| INMEM

    style GPT fill:#7c3aed,color:#fff,stroke:#5b21b6
    style SS fill:#6366f1,color:#fff,stroke:#4f46e5
    style FS fill:#6366f1,color:#fff,stroke:#4f46e5
    style STS fill:#6366f1,color:#fff,stroke:#4f46e5
    style CHROMA_PRODUCTS fill:#64748b,color:#fff,stroke:#475569
    style CHROMA_FAQ fill:#64748b,color:#fff,stroke:#475569
    style INMEM fill:#64748b,color:#fff,stroke:#475569
    style QF fill:#10b981,color:#fff,stroke:#059669
    style SA fill:#10b981,color:#fff,stroke:#059669
    style PG fill:#64748b,color:#fff,stroke:#475569
```

## Color Legend

| Color | Meaning |
|---|---|
| **Purple** | Supervisor / LLM nodes |
| **Blue** | Graph nodes (interrupt-driven) |
| **Yellow/Amber** | Interrupt pause points (user input required) |
| **Green** | MCP Apps (interactive UI panels) |
| **Indigo** | Backend services |
| **Gray** | Data stores and persistence |
| **Red** | Terminal node (submit) |

## Node Reference

| Node | Interrupt Type | MCP App | Service | User Actions |
|---|---|---|---|---|
| `supervisor_node` | — | — | OpenAI LLM (gpt-4o) | Free text, tool routing |
| `extract_search_intent` | — | — | OpenAI LLM | Auto: normalises free-text query, lifts `dp-NNN` study id |
| `mcp_prefetch_facets` | — | Search MCP App (tool call) | — | Auto: caches canonical chip ids/labels once per subgraph entry |
| `narrow_search` (default) | `narrow_message` | — | OpenAI LLM (gpt-4o, tool-calling) | Reply in chat — agent asks for missing facets and commits |
| `choose_domain` (nav-only) | `facet_selection` | — | — | Click domain chip — reachable only via `nav_intent` |
| `choose_anonymization` (nav-only) | `facet_selection` | — | — | Click anonymization chip — reachable only via `nav_intent` |
| `show_results_node` | `product_selection` | — | SearchService (ChromaDB) | Select products, Open Search Panel, Refine Filters |
| `search_app_node` | `mcp_app` | Search MCP App | — | Full search UI in panel, multi-select, confirm |
| `review_cart_node` | `cart_review` | — | — | Fill Forms, Add More, Change Selection |
| `fill_form_node` | `mcp_app` (loops) | Question Form MCP App | — | Fill form, submit, + Add More Products |
| `confirm_node` | `confirmation` | — | — | Submit, Edit Forms, + Add More Products |
| `submit_node` | — | — | — | Terminal: generates REQ-ID |
| `faq_node` | — | — | FaqService (ChromaDB) + LLM | Auto: returns answer |
| `status_check_node` | — | — | StatusService (in-memory) | Auto: returns status |

## Key Design Patterns

### 1. Conversational Funnel + MCP App Escalation
The flow starts with a textual narrowing conversation (the `narrow_search` subagent — plain chat, no chips by default), progresses to richer in-chat UI (product cards), and escalates to full MCP App panels (search app, form app) only when the interaction requires it. Chip-based facet pickers (`choose_domain`, `choose_anonymization`) survive only as `nav_intent` escape hatches for users who explicitly ask to "change the anonymization" mid-flow.

### 2. Universal "Back to narrow_search" Escape Hatch
Every node downstream of `narrow_search` can route back to it through `handle_navigation` → `invalidate_downstream_state` → `goto_target_step`, which clears stale state. This enables:
- **Refine Filters** from `show_results`
- **Add More Products** from `review_cart`, `fill_form`, and `confirm`
- **Change Selection** from `review_cart`

When the rewind target is `narrow_search`, the invalidation step intentionally **preserves** `selected_domains` and `selected_anonymization` so the agent keeps prior context for refinements; the user's typed hint is threaded through via the `narrow_refine_hint` state field.

### 3. Supervisor as Intent Classifier
The supervisor uses LLM tool-calling (gpt-4o) to classify user intent into one of three flows. If intent is unclear, it asks for clarification instead of guessing. After FAQ or Status Check, control returns to the supervisor for the next turn.

### 4. Interrupt-Driven Human-in-the-Loop
Every user-facing step uses LangGraph's `interrupt()` to pause execution, serialize state to PostgreSQL, and wait for the frontend to resume with user input. The graph never blocks — it checkpoints and exits, resuming exactly where it left off when the user responds. Each interrupt payload carries a `prompt_id` (UUID per call, plus the stable `"mcp_search"` id for the search panel); the frontend uses id equality to gate the actionability of historical bubbles, replacing superseded ones with a `User Skipped <Action>` notice.

### 5. Single-Interrupt-Per-Node Discipline
Nodes that need multiple round-trips with the user (notably `narrow_search`) implement one `interrupt()` per node execution and route back to themselves with `Command(goto=...)` after processing the resume. This avoids the multi-`interrupt()`-in-one-node rerun trap, where non-deterministic LLM calls during replay would invalidate cached interrupt correlation.
