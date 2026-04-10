# Data Governance Chat — Graph Architecture

## Full System Diagram

```mermaid
flowchart TB
    START((START))
    END_NODE((END))

    START --> SUPERVISOR

    subgraph PARENT["Parent Graph - Supervisor Router"]
        direction TB
        SUPERVISOR["supervisor_node\nLLM: gpt-4o-mini\nRoutes user intent via tool calls"]

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

        RA_START --> NARROW

        NARROW["narrow_node\nSelect Domain then Type\ninterrupt: facet_selection x2"]
        INT_NARROW1>"PAUSE: Domain chips\nR and D, Commercial, Safety, HR"]
        INT_NARROW2>"PAUSE: Type chips\nDDF, Default, Onyx, Any"]
        NARROW --- INT_NARROW1
        NARROW --- INT_NARROW2

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

        NARROW -->|"domain + type set"| SHOW
        SHOW -->|"products selected"| REVIEW
        REVIEW -->|"fill_forms"| FILL
        FILL -->|"all forms done"| CONFIRM
        CONFIRM -->|"confirm"| SUBMIT
        SUBMIT --> RA_END

        NARROW -->|"missing facet"| NARROW
        SHOW -->|"open_search"| SEARCH_APP
        SHOW -->|"refine_filters"| NARROW
        SEARCH_APP -->|"products selected"| REVIEW
        REVIEW -->|"add_more / change"| NARROW
        FILL -->|"next product"| FILL
        FILL -->|"add_more"| NARROW
        CONFIRM -->|"edit"| FILL
        CONFIRM -->|"add_more"| NARROW
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

    style NARROW fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style SHOW fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style SEARCH_APP fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style REVIEW fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style FILL fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style CONFIRM fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style SUBMIT fill:#ef4444,color:#fff,stroke:#dc2626,stroke-width:2px

    style INT_NARROW1 fill:#fef3c7,color:#000,stroke:#f59e0b,stroke-width:2px
    style INT_NARROW2 fill:#fef3c7,color:#000,stroke:#f59e0b,stroke-width:2px
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

        FS["facet_selection"] -->|"renders"| CHIPS["Clickable chip buttons\nin chat message"]

        PS["product_selection"] -->|"renders"| CARDS["Product cards with\ncheckboxes + action buttons\nRefine / Search / Add"]

        CR["cart_review"] -->|"renders"| CART["Cart summary with\naction buttons\nFill Forms / Add More / Change"]

        MA["mcp_app\nquestion-form"] -->|"opens"| FORM["Question Form\nMCP App in\nright panel"]

        MA2["mcp_app\nsearch-app"] -->|"opens"| SEARCH["Search Data Products\nMCP App in\nright panel"]

        CF["confirmation"] -->|"renders"| SUMMARY["Summary with\naction buttons\nSubmit / Edit / Add More"]
    end

    style FS fill:#f59e0b,color:#000,stroke:#d97706
    style PS fill:#f59e0b,color:#000,stroke:#d97706
    style CR fill:#f59e0b,color:#000,stroke:#d97706
    style MA fill:#f59e0b,color:#000,stroke:#d97706
    style MA2 fill:#f59e0b,color:#000,stroke:#d97706
    style CF fill:#f59e0b,color:#000,stroke:#d97706

    style CHIPS fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style CARDS fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style CART fill:#3b82f6,color:#fff,stroke:#1d4ed8
    style SUMMARY fill:#3b82f6,color:#fff,stroke:#1d4ed8

    style FORM fill:#10b981,color:#fff,stroke:#059669
    style SEARCH fill:#10b981,color:#fff,stroke:#059669
```

## Intent Switching — How Users Can Change Direction

The system supports mid-flow navigation at every step. Users can escape to earlier stages or switch intent entirely.

```mermaid
stateDiagram-v2
    state "Supervisor" as SUP
    state "Request Access Subgraph" as RA {
        state "narrow" as N
        state "show_results" as SR
        state "search_app" as SA
        state "review_cart" as RC
        state "fill_form" as FF
        state "confirm" as C
        state "submit" as S

        [*] --> N

        N --> N : missing facet
        N --> SR : both facets set

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

## Services and External Dependencies

```mermaid
flowchart LR
    subgraph LLMs
        GPT["OpenAI gpt-4o-mini"]
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
| `supervisor_node` | — | — | OpenAI LLM | Free text, tool routing |
| `narrow_node` | `facet_selection` x2 | — | — | Click domain chip, click type chip |
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
The flow starts with lightweight chat interactions (chip buttons for domain/type selection), progresses to richer in-chat UI (product cards), and escalates to full MCP App panels (search app, form app) only when the interaction requires it.

### 2. Universal "Back to Narrow" Escape Hatch
Every node downstream of `narrow` can route back to it by setting `current_step = "narrow"` and clearing `selected_domain`, `selected_type`, and `search_results`. This enables:
- **Refine Filters** from `show_results`
- **Add More Products** from `review_cart`, `fill_form`, and `confirm`
- **Change Selection** from `review_cart`

### 3. Supervisor as Intent Classifier
The supervisor uses LLM tool-calling to classify user intent into one of three flows. If intent is unclear, it asks for clarification instead of guessing. After FAQ or Status Check, control returns to the supervisor for the next turn.

### 4. Interrupt-Driven Human-in-the-Loop
Every user-facing step uses LangGraph's `interrupt()` to pause execution, serialize state to PostgreSQL, and wait for the frontend to resume with user input. The graph never blocks — it checkpoints and exits, resuming exactly where it left off when the user responds.
