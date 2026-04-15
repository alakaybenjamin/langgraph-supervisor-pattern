# Angular AG-UI Streaming Integration Guide

How to connect an Angular frontend to the `POST /api/v1/chat/stream` endpoint using the [AG-UI protocol](https://docs.ag-ui.com) — a standardised event schema for agent-to-user communication over Server-Sent Events (SSE).

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [What is the AG-UI Protocol?](#what-is-the-ag-ui-protocol)
3. [API Contract](#api-contract)
4. [SSE Wire Format](#sse-wire-format)
5. [TypeScript Interfaces — AG-UI Events](#typescript-interfaces--ag-ui-events)
6. [TypeScript Interfaces — Chat Models](#typescript-interfaces--chat-models)
7. [AgUiService — Low-Level SSE Consumer](#aguiservice--low-level-sse-consumer)
8. [ChatService — Application-Level Orchestrator](#chatservice--application-level-orchestrator)
9. [ChatComponent — Wiring the UI](#chatcomponent--wiring-the-ui)
10. [MessageComponent — Rendering Interrupts](#messagecomponent--rendering-interrupts)
11. [ChatInputComponent — Text Input](#chatinputcomponent--text-input)
12. [BFF Proxy Configuration](#bff-proxy-configuration)
13. [Environment Configuration](#environment-configuration)
14. [Key Concepts Explained](#key-concepts-explained)
15. [Comparison: AG-UI vs Native SSE](#comparison-ag-ui-vs-native-sse)
16. [Gotchas & Troubleshooting](#gotchas--troubleshooting)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────┐
│  BROWSER  (Angular 19 SPA)                       │
│                                                  │
│  ChatService (application logic)                 │
│    ├── sendMessage("hello")                      │
│    │     └── agUi.run(RunAgentInput, callback)   │
│    └── resumeWithData({value:"R&D"})             │
│          └── agUi.run(RunAgentInput, callback)   │
│                                                  │
│  AgUiService (SSE transport)                     │
│    ├── fetch() POST with Accept: text/event-stream│
│    ├── ReadableStream → line-by-line SSE parse   │
│    └── dispatch(AgUiEvent) → callback            │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  EXPRESS BFF  (localhost:4200)                    │
│                                                  │
│  /api/*  ──proxy──►  http://localhost:8000/api/v1/*│
│                                                  │
│  SSE passthrough (no buffering)                  │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  FASTAPI BACKEND  (localhost:8000)               │
│                                                  │
│  POST /api/v1/chat/stream                        │
│    → StreamingResponse (SSE)                     │
│    → ag_ui.encoder.EventEncoder encodes events   │
│    → LangGraph astream_events(version="v2")      │
│                                                  │
│  AG-UI events emitted:                           │
│    RUN_STARTED                                   │
│    STEP_STARTED / STEP_FINISHED                  │
│    TEXT_MESSAGE_START / CONTENT / END             │
│    CUSTOM (name="interrupt")                     │
│    RUN_FINISHED / RUN_ERROR                      │
└──────────────────────────────────────────────────┘
```

### Why AG-UI?

The [AG-UI protocol](https://docs.ag-ui.com) provides a **standardised event vocabulary** for agent-to-UI communication. Instead of inventing custom event names (`token`, `done`, `interrupt`), AG-UI defines a canonical set of event types (`TEXT_MESSAGE_CONTENT`, `STEP_STARTED`, `CUSTOM`, etc.) that any AG-UI-compatible client can consume.

Benefits over a bespoke SSE protocol:

- **Interoperability** — the same backend can serve any AG-UI-compatible frontend (React, Angular, Vue, or raw JS).
- **Step visibility** — first-class `STEP_STARTED` / `STEP_FINISHED` events let the UI show which graph node is executing without parsing opaque metadata.
- **Message lifecycle** — `TEXT_MESSAGE_START` / `CONTENT` / `END` give the client fine-grained control over when to create, append to, and finalise a message bubble.
- **Extensibility** — `CUSTOM` events carry application-specific payloads (interrupts, state snapshots) without polluting the core schema.

### Why SSE instead of WebSockets?

- **One-directional streaming** fits the LLM response pattern (server → client).
- **Standard HTTP** — works through corporate proxies, load balancers, and CDNs without special configuration.
- **POST body** — unlike native `EventSource` (GET-only), we use `fetch()` with a POST body, which lets us send the full request payload on every call.
- **Stateless** — each request is independent. The conversation state lives in the LangGraph checkpoint (PostgreSQL), not in a socket connection.

---

## What is the AG-UI Protocol?

AG-UI (Agent-User Interaction) is an open protocol that defines:

1. **`RunAgentInput`** — a standard request schema sent by the client (thread ID, run ID, messages, tools, state, context).
2. **A fixed set of event types** streamed back by the server:

| Event | Purpose |
|-------|---------|
| `RUN_STARTED` | Signals the beginning of a run |
| `STEP_STARTED` / `STEP_FINISHED` | Bracket a named processing step (graph node) |
| `TEXT_MESSAGE_START` | Opens a new assistant message (includes `messageId`, `role`) |
| `TEXT_MESSAGE_CONTENT` | Appends a text delta to the open message |
| `TEXT_MESSAGE_END` | Closes the open message |
| `STATE_SNAPSHOT` / `STATE_DELTA` | Full or incremental state updates (optional) |
| `CUSTOM` | Application-specific payload (we use this for LangGraph interrupts) |
| `RUN_FINISHED` | Signals normal completion |
| `RUN_ERROR` | Signals an error with a message string |

3. **`EventEncoder`** — a server-side encoder (provided by the `ag-ui-protocol` Python package) that serialises these typed events into SSE `data:` lines with the correct content type.

The Python backend depends on `ag-ui-protocol >= 0.1.15` and imports event classes and the encoder from `ag_ui.core` and `ag_ui.encoder`.

---

## API Contract

### Endpoint

```
POST /api/v1/chat/stream
Content-Type: application/json
Accept: text/event-stream
```

### Request Body — `RunAgentInput`

The request body follows the AG-UI `RunAgentInput` schema. Field names use **snake_case** because the FastAPI Pydantic model expects them.

```json
{
  "thread_id": "550e8400-e29b-41d4-a716-446655440000",
  "run_id": "a1b2c3d4-...",
  "messages": [
    { "id": "msg-uuid", "role": "user", "content": "I want to request access" }
  ],
  "tools": [],
  "state": {},
  "context": [],
  "forwarded_props": {}
}
```

| Field | Type | Description |
|-------|------|-------------|
| `thread_id` | `string` | UUID identifying the conversation thread |
| `run_id` | `string` | UUID identifying this specific run |
| `messages` | `AgUiMessage[]` | User messages to send (each with `id`, `role`, `content`) |
| `tools` | `unknown[]` | Tool definitions (unused in this app — empty array) |
| `state` | `object` | Arbitrary state; used for resume via `{ resume_data: {...} }` |
| `context` | `unknown[]` | Additional context (unused — empty array) |
| `forwarded_props` | `object` | Pass-through properties (unused — empty object) |

#### Send example

```json
{
  "thread_id": "550e8400-e29b-41d4-a716-446655440000",
  "run_id": "a1b2c3d4-...",
  "messages": [
    { "id": "msg-1", "role": "user", "content": "I want to request access to Clinical Data Products" }
  ],
  "tools": [],
  "state": {},
  "context": [],
  "forwarded_props": {}
}
```

#### Resume example

When resuming from an interrupt, `messages` is empty and `state` carries `resume_data`:

```json
{
  "thread_id": "550e8400-e29b-41d4-a716-446655440000",
  "run_id": "b2c3d4e5-...",
  "messages": [],
  "tools": [],
  "state": { "resume_data": { "value": "r_and_d", "facet": "domain" } },
  "context": [],
  "forwarded_props": {}
}
```

The backend detects `resume_data` in `state` and calls `graph.astream_events(Command(resume=resume_data), ...)` instead of invoking with a new `HumanMessage`.

---

## SSE Wire Format

The backend uses the AG-UI `EventEncoder` to serialise events. The wire format is standard SSE — each event is a `data:` line containing a JSON object, separated by blank lines:

```
data: {"type":"RUN_STARTED","threadId":"550e8400-...","runId":"a1b2c3d4-..."}

data: {"type":"STEP_STARTED","stepName":"supervisor"}

data: {"type":"TEXT_MESSAGE_START","messageId":"msg-uuid","role":"assistant"}

data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg-uuid","delta":"I can help"}

data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg-uuid","delta":" you with that!"}

data: {"type":"TEXT_MESSAGE_END","messageId":"msg-uuid"}

data: {"type":"STEP_FINISHED","stepName":"supervisor"}

data: {"type":"RUN_FINISHED","threadId":"550e8400-...","runId":"a1b2c3d4-..."}
```

Note: unlike the native SSE approach that uses `event:` + `data:` lines, the AG-UI encoder puts the event **type inside the JSON payload** as a `type` field. All lines use only `data:`.

### Event Examples

#### Text streaming (multiple content deltas)

```
data: {"type":"TEXT_MESSAGE_START","messageId":"abc-123","role":"assistant"}

data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"abc-123","delta":"I can help"}

data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"abc-123","delta":" you with that!"}

data: {"type":"TEXT_MESSAGE_END","messageId":"abc-123"}
```

#### Step visibility

```
data: {"type":"STEP_STARTED","stepName":"supervisor"}

data: {"type":"STEP_FINISHED","stepName":"supervisor"}

data: {"type":"STEP_STARTED","stepName":"narrow"}

data: {"type":"STEP_FINISHED","stepName":"narrow"}
```

#### Interrupt (CUSTOM event)

When the LangGraph graph pauses via `interrupt()`, the backend emits a `CUSTOM` event after the `astream_events` loop completes:

```
data: {"type":"CUSTOM","name":"interrupt","value":{"type":"facet_selection","facet":"domain","message":"What domain are you interested in?","options":[{"id":"r_and_d","label":"R&D / Clinical"},{"id":"commercial","label":"Commercial"}]}}
```

#### Error

```
data: {"type":"RUN_ERROR","message":"An error occurred: ..."}
```

### Interrupt Types

The `value.type` field inside a `CUSTOM` interrupt event determines what UI to render:

| `value.type` | UI to Render | Resume Payload |
|--------------|-------------|----------------|
| `facet_selection` | Clickable chip buttons | `{ "value": "r_and_d", "facet": "domain" }` |
| `product_selection` | Product cards with checkboxes | `{ "action": "select", "products": [...] }` |
| `cart_review` | Cart summary with action buttons | `{ "action": "fill_forms" }` |
| `mcp_app` | Opens MCP App in side panel | `{ "form_data": "...", "submitted": true }` |
| `confirmation` | Submit / edit / add-more buttons | `{ "confirmed": true, "action": "confirm" }` |

---

## TypeScript Interfaces — AG-UI Events

Create `core/models/ag-ui.model.ts`:

```typescript
export enum AgUiEventType {
  RUN_STARTED = 'RUN_STARTED',
  RUN_FINISHED = 'RUN_FINISHED',
  RUN_ERROR = 'RUN_ERROR',
  STEP_STARTED = 'STEP_STARTED',
  STEP_FINISHED = 'STEP_FINISHED',
  TEXT_MESSAGE_START = 'TEXT_MESSAGE_START',
  TEXT_MESSAGE_CONTENT = 'TEXT_MESSAGE_CONTENT',
  TEXT_MESSAGE_END = 'TEXT_MESSAGE_END',
  STATE_SNAPSHOT = 'STATE_SNAPSHOT',
  STATE_DELTA = 'STATE_DELTA',
  CUSTOM = 'CUSTOM',
}

export interface BaseAgUiEvent {
  type: AgUiEventType;
  timestamp?: number;
}

export interface RunStartedEvent extends BaseAgUiEvent {
  type: AgUiEventType.RUN_STARTED;
  threadId: string;
  runId: string;
}

export interface RunFinishedEvent extends BaseAgUiEvent {
  type: AgUiEventType.RUN_FINISHED;
  threadId: string;
  runId: string;
}

export interface RunErrorEvent extends BaseAgUiEvent {
  type: AgUiEventType.RUN_ERROR;
  message: string;
  code?: string;
}

export interface StepStartedEvent extends BaseAgUiEvent {
  type: AgUiEventType.STEP_STARTED;
  stepName: string;
}

export interface StepFinishedEvent extends BaseAgUiEvent {
  type: AgUiEventType.STEP_FINISHED;
  stepName: string;
}

export interface TextMessageStartEvent extends BaseAgUiEvent {
  type: AgUiEventType.TEXT_MESSAGE_START;
  messageId: string;
  role: 'assistant' | 'user' | 'system' | 'developer';
}

export interface TextMessageContentEvent extends BaseAgUiEvent {
  type: AgUiEventType.TEXT_MESSAGE_CONTENT;
  messageId: string;
  delta: string;
}

export interface TextMessageEndEvent extends BaseAgUiEvent {
  type: AgUiEventType.TEXT_MESSAGE_END;
  messageId: string;
}

export interface StateSnapshotEvent extends BaseAgUiEvent {
  type: AgUiEventType.STATE_SNAPSHOT;
  snapshot: unknown;
}

export interface StateDeltaEvent extends BaseAgUiEvent {
  type: AgUiEventType.STATE_DELTA;
  delta: unknown[];
}

export interface CustomAgUiEvent extends BaseAgUiEvent {
  type: AgUiEventType.CUSTOM;
  name: string;
  value: unknown;
}

export type AgUiEvent =
  | RunStartedEvent
  | RunFinishedEvent
  | RunErrorEvent
  | StepStartedEvent
  | StepFinishedEvent
  | TextMessageStartEvent
  | TextMessageContentEvent
  | TextMessageEndEvent
  | StateSnapshotEvent
  | StateDeltaEvent
  | CustomAgUiEvent;

export interface AgUiMessage {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'developer';
  content: string;
}

/**
 * Body sent to POST /chat/stream.
 *
 * Uses snake_case because the FastAPI Pydantic model RunAgentInput
 * expects snake_case fields.
 */
export interface RunAgentInput {
  thread_id: string;
  run_id: string;
  messages: AgUiMessage[];
  tools: unknown[];
  state: unknown;
  context: unknown[];
  forwarded_props: unknown;
}
```

Note: the event **wire format uses camelCase** (`stepName`, `messageId`, `threadId`) — this matches the AG-UI Python `EventEncoder` output. The **request body uses snake_case** (`thread_id`, `run_id`) to match the FastAPI Pydantic model.

---

## TypeScript Interfaces — Chat Models

Create `core/models/chat.model.ts`:

```typescript
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  interrupt?: InterruptPayload;
}

export interface InterruptPayload {
  type: string;
  interrupt_value: Record<string, unknown>;
  thread_id: string;
}

export interface ChatResponse {
  type: 'message' | 'interrupt' | 'error';
  content: string;
  thread_id: string;
  interrupt?: InterruptPayload | null;
}
```

---

## AgUiService — Low-Level SSE Consumer

This service handles the **transport layer**: it POSTs a `RunAgentInput` to the streaming endpoint, parses the SSE response line-by-line, deserialises each JSON payload into an `AgUiEvent`, and dispatches it via a callback.

It lives at `core/services/ag-ui.service.ts`.

### Why a separate service?

Separating SSE transport from application logic (message state, interrupt handling) keeps each layer testable and swappable. `AgUiService` knows nothing about `ChatMessage` or `InterruptPayload` — it only speaks the AG-UI protocol.

### Complete code

```typescript
import { Injectable, signal } from '@angular/core';
import { environment } from '../../../environments/environment';
import {
  AgUiEvent,
  AgUiEventType,
  RunAgentInput,
} from '../models/ag-ui.model';

export type AgUiEventCallback = (event: AgUiEvent) => void;

@Injectable({ providedIn: 'root' })
export class AgUiService {
  currentStep = signal<string | null>(null);
  running = signal<boolean>(false);

  private readonly endpoint = `${environment.apiBaseUrl}/chat/stream`;
  private abortController: AbortController | null = null;

  async run(input: RunAgentInput, onEvent: AgUiEventCallback): Promise<void> {
    this.abort();
    this.abortController = new AbortController();
    this.running.set(true);
    this.currentStep.set(null);

    try {
      const resp = await fetch(this.endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify(input),
        signal: this.abortController.signal,
      });

      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`AG-UI request failed (${resp.status}): ${text}`);
      }

      await this.consumeStream(resp.body!, onEvent);
    } catch (err: any) {
      if (err.name === 'AbortError') return;
      throw err;
    } finally {
      this.running.set(false);
      this.currentStep.set(null);
      this.abortController = null;
    }
  }

  abort(): void {
    this.abortController?.abort();
    this.abortController = null;
  }

  private async consumeStream(
    body: ReadableStream<Uint8Array>,
    onEvent: AgUiEventCallback,
  ): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      let currentData = '';
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          currentData += line.slice(6);
        } else if (line === '' && currentData) {
          this.dispatch(currentData, onEvent);
          currentData = '';
        }
      }
    }

    if (buffer.trim()) {
      const remaining = buffer.trim();
      if (remaining.startsWith('data: ')) {
        this.dispatch(remaining.slice(6), onEvent);
      }
    }
  }

  private dispatch(raw: string, onEvent: AgUiEventCallback): void {
    try {
      const event = JSON.parse(raw) as AgUiEvent;

      if (event.type === AgUiEventType.STEP_STARTED) {
        this.currentStep.set(
          (event as { stepName: string }).stepName,
        );
      } else if (event.type === AgUiEventType.STEP_FINISHED) {
        this.currentStep.set(null);
      }

      onEvent(event);
    } catch {
      // malformed line — skip
    }
  }
}
```

### How SSE parsing works

```
Raw stream bytes
     │
     ▼
TextDecoder.decode(chunk, { stream: true })
     │
     ▼
Append to buffer, split on '\n'
     │
     ├── Line starts with "data: "  →  accumulate JSON string
     ├── Empty line ("")             →  dispatch accumulated data, reset
     └── Incomplete line             →  keep in buffer for next chunk
     │
     ▼
JSON.parse(accumulated) → AgUiEvent
     │
     ├── STEP_STARTED  →  update currentStep signal
     ├── STEP_FINISHED →  clear currentStep signal
     └── all events    →  invoke callback
```

Key difference from native SSE: the AG-UI format does **not** use `event:` lines. The event type lives **inside** the JSON `data:` payload as the `type` field. This simplifies parsing — every meaningful line is `data: <json>`.

---

## ChatService — Application-Level Orchestrator

This service consumes `AgUiEvent` objects from `AgUiService` and translates them into application state: messages, loading indicators, interrupts.

It lives at `core/services/chat.service.ts`.

### Complete code

```typescript
import { inject, Injectable, signal } from '@angular/core';
import {
  ChatMessage,
  ChatResponse,
  InterruptPayload,
} from '../models/chat.model';
import {
  AgUiEvent,
  AgUiEventType,
  CustomAgUiEvent,
  RunAgentInput,
  TextMessageContentEvent,
  TextMessageStartEvent,
} from '../models/ag-ui.model';
import { AgUiService } from './ag-ui.service';
import { v4 as uuidv4 } from 'uuid';

@Injectable({ providedIn: 'root' })
export class ChatService {
  messages = signal<ChatMessage[]>([]);
  threadId = signal<string>(uuidv4());
  loading = signal<boolean>(false);
  currentInterrupt = signal<ChatResponse | null>(null);
  currentStep = signal<string | null>(null);

  private agUi = inject(AgUiService);
  private streamingMessageId: string | null = null;

  async sendMessage(content: string): Promise<void> {
    const userMsg: ChatMessage = {
      role: 'user',
      content,
      timestamp: new Date(),
    };
    this.messages.update((msgs) => [...msgs, userMsg]);
    this.loading.set(true);

    const input: RunAgentInput = {
      thread_id: this.threadId(),
      run_id: uuidv4(),
      messages: [{ id: uuidv4(), role: 'user', content }],
      tools: [],
      state: {},
      context: [],
      forwarded_props: {},
    };

    try {
      await this.agUi.run(input, (event) => this.handleEvent(event));
    } catch (err: any) {
      this.appendSystemMessage(`Error: ${err.message || err}`);
    } finally {
      this.loading.set(false);
      this.streamingMessageId = null;
    }
  }

  async resumeWithData(data: Record<string, unknown>): Promise<void> {
    this.loading.set(true);
    this.currentInterrupt.set(null);

    const input: RunAgentInput = {
      thread_id: this.threadId(),
      run_id: uuidv4(),
      messages: [],
      tools: [],
      state: { resume_data: data },
      context: [],
      forwarded_props: {},
    };

    try {
      await this.agUi.run(input, (event) => this.handleEvent(event));
    } catch (err: any) {
      this.appendSystemMessage(`Resume error: ${err.message || err}`);
    } finally {
      this.loading.set(false);
      this.streamingMessageId = null;
    }
  }

  newThread(): void {
    this.agUi.abort();
    this.messages.set([]);
    this.threadId.set(uuidv4());
    this.currentInterrupt.set(null);
    this.currentStep.set(null);
    this.streamingMessageId = null;
  }

  private handleEvent(event: AgUiEvent): void {
    switch (event.type) {
      case AgUiEventType.TEXT_MESSAGE_START:
        this.onTextStart(event as TextMessageStartEvent);
        break;

      case AgUiEventType.TEXT_MESSAGE_CONTENT:
        this.onTextContent(event as TextMessageContentEvent);
        break;

      case AgUiEventType.TEXT_MESSAGE_END:
        this.streamingMessageId = null;
        break;

      case AgUiEventType.STEP_STARTED:
        this.currentStep.set((event as { stepName: string }).stepName);
        break;

      case AgUiEventType.STEP_FINISHED:
        this.currentStep.set(null);
        break;

      case AgUiEventType.CUSTOM:
        this.onCustom(event as CustomAgUiEvent);
        break;

      case AgUiEventType.RUN_ERROR:
        this.appendSystemMessage(
          `Error: ${(event as { message: string }).message}`,
        );
        break;

      default:
        break;
    }
  }

  private onTextStart(event: TextMessageStartEvent): void {
    this.streamingMessageId = event.messageId;
    const msg: ChatMessage = {
      role: 'assistant',
      content: '',
      timestamp: new Date(),
    };
    this.messages.update((msgs) => [...msgs, msg]);
  }

  private onTextContent(event: TextMessageContentEvent): void {
    if (this.streamingMessageId !== event.messageId) return;
    this.messages.update((msgs) => {
      const copy = [...msgs];
      const last = copy[copy.length - 1];
      if (last?.role === 'assistant') {
        copy[copy.length - 1] = {
          ...last,
          content: last.content + event.delta,
        };
      }
      return copy;
    });
  }

  private onCustom(event: CustomAgUiEvent): void {
    if (event.name !== 'interrupt') return;

    const interruptValue = event.value as Record<string, unknown>;
    const interrupt: InterruptPayload = {
      type: 'interrupt',
      interrupt_value: interruptValue,
      thread_id: this.threadId(),
    };

    const resp: ChatResponse = {
      type: 'interrupt',
      content: '',
      thread_id: this.threadId(),
      interrupt,
    };

    this.currentInterrupt.set(resp);

    const assistantMsg: ChatMessage = {
      role: 'assistant',
      content:
        interruptValue['message']?.toString() ||
        'Please complete the action in the panel.',
      timestamp: new Date(),
      interrupt,
    };
    this.messages.update((msgs) => [...msgs, assistantMsg]);
  }

  private appendSystemMessage(text: string): void {
    const msg: ChatMessage = {
      role: 'system',
      content: text,
      timestamp: new Date(),
    };
    this.messages.update((msgs) => [...msgs, msg]);
  }
}
```

### How signals drive the UI

```
messages signal ──────►  @for loop in ChatComponent ──► MessageComponent[]
loading signal  ──────►  typing indicator / input disabled
currentStep     ─────►  step label next to typing dots
currentInterrupt ─────►  McpPanelComponent (effect watches this)
threadId signal  ─────►  included in every RunAgentInput body
```

### Two-service split: AgUiService vs ChatService

```
┌─────────────────────────────┐     ┌─────────────────────────────┐
│        AgUiService          │     │        ChatService           │
│  (transport / protocol)     │     │  (application / state)       │
├─────────────────────────────┤     ├─────────────────────────────┤
│  • fetch() + SSE parsing    │     │  • messages signal           │
│  • RunAgentInput → stream   │     │  • loading / currentStep     │
│  • currentStep signal       │────►│  • currentInterrupt          │
│  • AbortController          │     │  • sendMessage / resumeWith  │
│  • AgUiEvent dispatch       │     │  • handleEvent (switch)      │
│  • Knows nothing about Chat │     │  • Knows nothing about SSE   │
└─────────────────────────────┘     └─────────────────────────────┘
```

This separation means you can swap `AgUiService` for a WebSocket transport or a mock without touching `ChatService`, and you can test `ChatService` by feeding it `AgUiEvent` objects directly.

---

## ChatComponent — Wiring the UI

This is the top-level chat container. It renders the message list, the step-aware typing indicator, and handles user actions that should resume the graph.

`features/chat/chat.component.ts`:

```typescript
import {
  Component,
  ElementRef,
  ViewChild,
  AfterViewChecked,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatService } from '../../core/services/chat.service';
import { MessageComponent } from './message/message.component';
import { ChatInputComponent } from './chat-input/chat-input.component';

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [CommonModule, MessageComponent, ChatInputComponent],
  template: `
    <div class="chat-container">
      <div class="chat-header">
        <h2>Data Governance Assistant</h2>
        <button class="new-thread-btn" (click)="chatService.newThread()">
          + New Chat
        </button>
      </div>

      <div class="messages-area" #messagesArea>
        @if (chatService.messages().length === 0) {
          <div class="empty-state">
            <h3>Welcome to Data Governance</h3>
            <p>I can help you with:</p>
            <ul>
              <li>Request access to data products</li>
              <li>Answer questions about data governance</li>
              <li>Check the status of your requests</li>
            </ul>
          </div>
        }

        @for (msg of chatService.messages(); track $index) {
          <app-message
            [msg]="msg"
            (productSelected)="onProductSelected($event)"
            (confirmed)="onConfirmed($event)"
            (facetSelected)="onFacetSelected($event)"
            (cartAction)="onCartAction($event)"
            (openSearchPanel)="onOpenSearch()"
            (refineSearch)="onRefineSearch()"
          />
        }

        <!-- Step-aware typing indicator -->
        @if (chatService.loading()) {
          <div class="typing-indicator">
            @if (chatService.currentStep()) {
              <span class="step-label">
                {{ stepLabel(chatService.currentStep()!) }}
              </span>
            }
            <div class="dot"></div>
            <div class="dot"></div>
            <div class="dot"></div>
          </div>
        }
      </div>

      <app-chat-input
        [disabled]="chatService.loading()"
        (messageSent)="onSend($event)"
      />
    </div>
  `,
})
export class ChatComponent implements AfterViewChecked {
  chatService = inject(ChatService);

  @ViewChild('messagesArea') private messagesArea!: ElementRef;

  ngAfterViewChecked(): void {
    this.scrollToBottom();
  }

  /**
   * Maps LangGraph node names to user-friendly labels.
   * Shown next to the typing dots via STEP_STARTED events.
   */
  private readonly stepLabels: Record<string, string> = {
    supervisor: 'Thinking',
    faq: 'Searching knowledge base',
    status_check: 'Checking status',
    narrow: 'Narrowing search',
    show_results: 'Showing results',
    search_app: 'Searching',
    review_cart: 'Reviewing cart',
    fill_form: 'Filling form',
    confirm: 'Confirming',
    submit: 'Submitting',
  };

  stepLabel(step: string): string {
    return this.stepLabels[step] ?? step.replace(/_/g, ' ');
  }

  onSend(message: string): void {
    const interrupt = this.chatService.currentInterrupt();
    if (interrupt?.interrupt) {
      const interruptType = interrupt.interrupt.interrupt_value?.['type'];
      const lower = message.toLowerCase();

      if (interruptType === 'mcp_app') {
        this.addUserMessageAndResume(message, {
          action: 'user_message', text: message,
        });
        return;
      }

      const refineIntent = this.matchesIntent(lower, [
        'refine', 'change filter', 'different filter', 'try again',
        'go back', 'back to search', 'search again', 'start over',
      ]);

      if (interruptType === 'facet_selection' && refineIntent) {
        this.addUserMessageAndResume(message, { value: 'all' });
        return;
      }
    }
    this.chatService.sendMessage(message);
  }

  private addUserMessageAndResume(
    text: string,
    data: Record<string, unknown>,
  ): void {
    this.chatService.messages.update((msgs) => [
      ...msgs,
      { role: 'user', content: text, timestamp: new Date() },
    ]);
    this.chatService.resumeWithData(data);
  }

  private matchesIntent(text: string, patterns: string[]): boolean {
    return patterns.some((p) => text.includes(p));
  }

  onProductSelected(data: Record<string, unknown>): void {
    this.chatService.resumeWithData(data);
  }

  onConfirmed(yes: boolean): void {
    this.chatService.resumeWithData({
      confirmed: yes,
      action: yes ? 'confirm' : 'edit',
    });
  }

  onFacetSelected(data: Record<string, unknown>): void {
    this.chatService.resumeWithData(data);
  }

  onCartAction(data: Record<string, unknown>): void {
    this.chatService.resumeWithData(data);
  }

  onOpenSearch(): void {
    this.chatService.resumeWithData({ action: 'open_search' });
  }

  onRefineSearch(): void {
    this.chatService.resumeWithData({ action: 'refine_filters' });
  }

  private scrollToBottom(): void {
    try {
      this.messagesArea.nativeElement.scrollTop =
        this.messagesArea.nativeElement.scrollHeight;
    } catch (e) {}
  }
}
```

### The resume flow

```
User clicks chip "R&D / Clinical"
        │
        ▼
MessageComponent emits (facetSelected) = { value: "r_and_d", facet: "domain" }
        │
        ▼
ChatComponent.onFacetSelected() calls chatService.resumeWithData(data)
        │
        ▼
ChatService.resumeWithData():
  1. Clears currentInterrupt signal
  2. Builds RunAgentInput with state: { resume_data: data }
  3. Calls agUi.run(input, handleEvent)
        │
        ▼
AgUiService.run():
  POST /api/chat/stream  { ..., state: { resume_data: {...} }, messages: [] }
        │
        ▼
Backend: graph.astream_events(Command(resume=resume_data), config)
  → interrupt() returns resume_data to the paused node
  → node processes it, graph continues
  → new AG-UI events stream back (STEP, TEXT_MESSAGE, CUSTOM, etc.)
```

---

## MessageComponent — Rendering Interrupts

Each `ChatMessage` might carry an `interrupt` payload. The `MessageComponent` inspects `msg.interrupt.interrupt_value.type` to decide what interactive UI to show below the message text.

`features/chat/message/message.component.ts`:

```typescript
import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatMessage } from '../../../core/models/chat.model';

@Component({
  selector: 'app-message',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="message" [class]="msg.role">
      <div class="avatar">
        {{ msg.role === 'user' ? 'U' : msg.role === 'assistant' ? 'A' : 'S' }}
      </div>
      <div class="bubble">
        <div class="content" [innerHTML]="formatContent(msg.content)"></div>

        <!-- FACET SELECTION: clickable chip buttons -->
        @if (facetOptions().length > 0 && !resolved) {
          <div class="facet-options">
            @for (opt of facetOptions(); track opt.id) {
              <button class="facet-chip" (click)="selectFacet(opt.id)">
                {{ opt.label }}
              </button>
            }
          </div>
        }

        <!-- PRODUCT SELECTION: multi-select cards -->
        @if (isProductSelection() && !resolved) {
          <div class="product-cards">
            @for (p of products(); track p.metadata?.id) {
              <button
                class="product-card"
                [class.selected]="isProductSelected(p)"
                (click)="toggleProduct(p)"
              >
                <div class="product-id">{{ p.metadata?.id }}</div>
                <div class="product-desc">{{ truncate(p.content, 100) }}</div>
              </button>
            }
            <button
              class="action-btn primary"
              [disabled]="selectedProducts.length === 0"
              (click)="confirmProductSelection()"
            >
              Add {{ selectedProducts.length || '' }} to Request
            </button>
          </div>
        }

        <!-- CART REVIEW: action buttons -->
        @if (cartActions().length > 0 && !resolved) {
          <div class="cart-actions">
            @for (action of cartActions(); track action.id) {
              <button
                class="action-btn"
                [class.primary]="action.id === 'fill_forms'"
                (click)="selectCartAction(action.id)"
              >
                {{ action.label }}
              </button>
            }
          </div>
        }

        <!-- CONFIRMATION: yes / no buttons -->
        @if (isConfirmation() && !resolved) {
          <div class="confirm-actions">
            <button class="confirm-btn yes" (click)="confirm(true)">
              Yes, submit
            </button>
            <button class="confirm-btn no" (click)="confirm(false)">
              Go back and edit
            </button>
          </div>
        }

        @if (resolved) {
          <div class="resolved-badge">Completed</div>
        }

        <div class="time">{{ msg.timestamp | date : 'HH:mm' }}</div>
      </div>
    </div>
  `,
})
export class MessageComponent {
  @Input({ required: true }) msg!: ChatMessage;
  @Output() facetSelected = new EventEmitter<Record<string, unknown>>();
  @Output() productSelected = new EventEmitter<Record<string, unknown>>();
  @Output() cartAction = new EventEmitter<Record<string, unknown>>();
  @Output() confirmed = new EventEmitter<boolean>();
  @Output() openSearchPanel = new EventEmitter<void>();
  @Output() refineSearch = new EventEmitter<void>();

  resolved = false;
  selectedProducts: any[] = [];

  facetOptions(): { id: string; label: string }[] {
    const val = this.msg.interrupt?.interrupt_value;
    if (val?.['type'] === 'facet_selection' && val?.['options']) {
      return val['options'] as { id: string; label: string }[];
    }
    return [];
  }

  isProductSelection(): boolean {
    return this.msg.interrupt?.interrupt_value?.['type'] === 'product_selection';
  }

  products(): any[] {
    const val = this.msg.interrupt?.interrupt_value;
    if (val?.['type'] === 'product_selection' && val?.['products']) {
      return val['products'] as any[];
    }
    return [];
  }

  cartActions(): { id: string; label: string }[] {
    const val = this.msg.interrupt?.interrupt_value;
    if (val?.['type'] === 'cart_review' && val?.['actions']) {
      return val['actions'] as { id: string; label: string }[];
    }
    return [];
  }

  isConfirmation(): boolean {
    return this.msg.interrupt?.interrupt_value?.['type'] === 'confirmation';
  }

  selectFacet(value: string): void {
    this.resolved = true;
    const facet = this.msg.interrupt?.interrupt_value?.['facet'] as string;
    this.facetSelected.emit({ value, facet });
  }

  toggleProduct(product: any): void {
    const idx = this.selectedProducts.findIndex(
      (p: any) => p.metadata?.id === product.metadata?.id
    );
    if (idx >= 0) {
      this.selectedProducts = this.selectedProducts.filter((_, i) => i !== idx);
    } else {
      this.selectedProducts = [...this.selectedProducts, product];
    }
  }

  isProductSelected(product: any): boolean {
    return this.selectedProducts.some(
      (p: any) => p.metadata?.id === product.metadata?.id
    );
  }

  confirmProductSelection(): void {
    this.resolved = true;
    this.productSelected.emit({
      action: 'select',
      products: this.selectedProducts,
    });
  }

  selectCartAction(action: string): void {
    this.resolved = true;
    this.cartAction.emit({ action });
  }

  confirm(yes: boolean): void {
    this.resolved = true;
    this.confirmed.emit(yes);
  }

  truncate(text: string, maxLen: number): string {
    if (!text) return '';
    return text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
  }

  formatContent(content: string): string {
    return content
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>');
  }
}
```

### How interrupt → UI rendering works

```
AG-UI event: CUSTOM { name: "interrupt", value: {...} }
  │
  ▼
ChatService.handleEvent → case CUSTOM → onCustom(event)
  │
  ├── Sets currentInterrupt signal (for McpPanelComponent)
  │
  └── Appends assistant ChatMessage with:
        content = interruptValue['message']
        interrupt = {
          type: "interrupt",
          interrupt_value: {
            type: "facet_selection",     ◄── This drives the template
            facet: "domain",
            message: "What domain?",
            options: [                   ◄── These become chips
              { id: "r_and_d", label: "R&D / Clinical" },
              { id: "commercial", label: "Commercial" },
            ]
          },
          thread_id: "..."
        }

Template evaluation:
  facetOptions() reads msg.interrupt.interrupt_value
    → type === "facet_selection" && options exists
    → returns the options array
    → @for renders a chip button for each option
```

---

## ChatInputComponent — Text Input

A simple text input with enter-to-send. `features/chat/chat-input/chat-input.component.ts`:

```typescript
import { Component, EventEmitter, Output, Input } from '@angular/core';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-chat-input',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="input-bar">
      <input
        type="text"
        [(ngModel)]="text"
        (keydown.enter)="send()"
        [disabled]="disabled"
        placeholder="Type your message..."
        class="input-field"
      />
      <button
        (click)="send()"
        [disabled]="disabled || !text.trim()"
        class="send-btn"
      >
        Send
      </button>
    </div>
  `,
})
export class ChatInputComponent {
  @Output() messageSent = new EventEmitter<string>();
  @Input() disabled = false;

  text = '';

  send(): void {
    const trimmed = this.text.trim();
    if (trimmed) {
      this.messageSent.emit(trimmed);
      this.text = '';
    }
  }
}
```

---

## BFF Proxy Configuration

The Angular app is served by an Express BFF that proxies API requests to the FastAPI backend. The path rewrite converts `/api/*` to `/api/v1/*`.

`frontend/server/src/index.ts`:

```typescript
import express from 'express';
import cors from 'cors';
import path from 'path';
import { createProxyMiddleware } from 'http-proxy-middleware';

const app = express();
const PORT = process.env.PORT || 4200;
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

app.use(cors());

app.use(
  '/api',
  createProxyMiddleware({
    target: BACKEND_URL,
    changeOrigin: true,
    pathRewrite: (_path) => `/api/v1${_path}`,
  })
);
```

### URL mapping

| Browser request | BFF proxy | Backend |
|----------------|-----------|---------|
| `POST /api/chat/stream` | rewrites path | `POST /api/v1/chat/stream` |
| `POST /mcp/search-app` | path preserved | `POST /mcp/search-app` |

### SSE proxy note

The `http-proxy-middleware` library passes through streaming responses by default when using `createProxyMiddleware` with Express. If you observe that events arrive in a single burst rather than incrementally, add explicit header flushing:

```typescript
app.use(
  '/api',
  createProxyMiddleware({
    target: BACKEND_URL,
    changeOrigin: true,
    pathRewrite: (_path) => `/api/v1${_path}`,
    on: {
      proxyRes: (proxyRes, _req, res) => {
        const ct = proxyRes.headers['content-type'] || '';
        if (ct.includes('text/event-stream')) {
          (res as any).flushHeaders?.();
        }
      },
    },
  })
);
```

---

## Environment Configuration

`environments/environment.ts`:

```typescript
export const environment = {
  production: false,
  apiBaseUrl: '/api',
  mcpBaseUrl: '/mcp/question-form',
};
```

The `apiBaseUrl` is `/api` (relative). The BFF proxy handles the rewrite to `/api/v1`. In production, this would point to the actual backend URL.

---

## Key Concepts Explained

### 1. Thread ID — Conversation Identity

Every conversation has a UUID `thread_id`. The LangGraph backend uses this to:
- **Checkpoint state** to PostgreSQL after every node execution
- **Resume** from exactly where it left off when the frontend sends `resume_data` in the `state` field

The frontend generates a new `thread_id` (via `uuidv4()`) when starting a new conversation.

### 2. Run ID — Request Identity

Each call to the endpoint gets a unique `run_id`. This lets the backend (and any observability tooling) correlate all events from a single request. A new `run_id` is generated for every `sendMessage()` and `resumeWithData()` call.

### 3. Message ID — Streaming Message Identity

The `TEXT_MESSAGE_START` event includes a `messageId`. All subsequent `TEXT_MESSAGE_CONTENT` events reference this ID. This allows the frontend to:
- Ignore deltas for messages it's not tracking (e.g. from a previous aborted stream)
- Know when a message is complete (`TEXT_MESSAGE_END`)
- Support multiple assistant messages in a single run (the backend generates a new `messageId` when a step boundary resets the message)

### 4. Signals — Reactive State

Angular signals are the reactive primitive used throughout. When a signal's value changes, any component template that reads it re-renders automatically.

```typescript
messages = signal<ChatMessage[]>([]);
loading = signal<boolean>(false);
currentInterrupt = signal<ChatResponse | null>(null);
currentStep = signal<string | null>(null);
```

### 5. Immutable Updates

Signal-based change detection relies on **reference equality**. To trigger a re-render, you must create a new array/object:

```typescript
// CORRECT — new array, new last element
this.messages.update((msgs) => {
  const copy = [...msgs];
  const last = copy[copy.length - 1];
  copy[copy.length - 1] = { ...last, content: last.content + delta };
  return copy;
});

// WRONG — mutating in place, signal won't detect the change
this.messages.update((msgs) => {
  msgs[msgs.length - 1].content += delta;
  return msgs;
});
```

### 6. The AG-UI Message Lifecycle

Unlike the native SSE approach where a placeholder message is pre-created and tokens append to it, the AG-UI approach creates the message **on demand** when `TEXT_MESSAGE_START` arrives:

```
TEXT_MESSAGE_START { messageId: "abc", role: "assistant" }
  → ChatService creates new empty ChatMessage, stores messageId

TEXT_MESSAGE_CONTENT { messageId: "abc", delta: "I can" }
  → Appends " I can" to last assistant message (if messageId matches)

TEXT_MESSAGE_CONTENT { messageId: "abc", delta: " help you" }
  → Appends " help you"

TEXT_MESSAGE_END { messageId: "abc" }
  → Clears streamingMessageId (message is finalised)
```

This is more robust than a placeholder because the frontend never shows an empty bubble — the message only appears once the backend confirms it's starting to generate text.

### 7. The Interrupt Lifecycle

```
1. Backend graph node calls interrupt({ type: "facet_selection", ... })
2. Graph freezes, state saved to PostgreSQL
3. astream_events() loop ends (no interrupt in the stream itself)
4. Backend calls aget_state(config) → finds pending interrupt
5. Backend emits: CUSTOM { name: "interrupt", value: { type: "facet_selection", ... } }
6. Frontend AgUiService dispatches CUSTOM event
7. Frontend ChatService.onCustom():
   a. Sets currentInterrupt signal (for McpPanelComponent)
   b. Appends assistant ChatMessage with interrupt payload
8. MessageComponent renders interactive UI based on interrupt_value.type
9. User clicks a chip / selects products / confirms
10. Component emits event → ChatComponent calls chatService.resumeWithData(data)
11. ChatService builds RunAgentInput with state: { resume_data: data }
12. AgUiService POSTs to /chat/stream
13. Backend: astream_events(Command(resume=data), config)
    → interrupt() returns data → node processes → graph continues
14. New AG-UI events stream back
```

### 8. Node Filtering in the Backend

The `AgUiService` backend only emits `STEP_STARTED` / `STEP_FINISHED` for **real graph nodes**. Internal LangGraph machinery is filtered out:

```python
_SKIP_NODE_NAMES = frozenset({
    "LangGraph", "ChannelRead", "ChannelWrite",
    "__start__", "__end__",
    "RunnableSequence", "ChatPromptTemplate",
    "ChatOpenAI", "AzureChatOpenAI",
})
```

This ensures the frontend typing indicator shows meaningful labels like "Thinking", "Narrowing search", "Reviewing cart" — not internal plumbing names.

---

## Comparison: AG-UI vs Native SSE

This codebase has two streaming implementations. Here is how they compare:

| Aspect | AG-UI Protocol | Native SSE |
|--------|---------------|------------|
| **Wire format** | `data:` lines only; event type inside JSON `type` field | `event:` + `data:` lines; event type in SSE `event:` header |
| **Event schema** | Standardised (`RUN_STARTED`, `TEXT_MESSAGE_CONTENT`, etc.) | Custom (`token`, `done`, `interrupt`, `error`) |
| **Message creation** | On-demand via `TEXT_MESSAGE_START` | Pre-created placeholder before streaming |
| **Step visibility** | Built-in `STEP_STARTED` / `STEP_FINISHED` events | Not available |
| **Request body** | AG-UI `RunAgentInput` (thread_id, run_id, messages, state, ...) | Custom `ChatRequest` (action, message, resume_data, ...) |
| **Resume mechanism** | `state: { resume_data: {...} }` with empty messages | `action: "resume"` with `resume_data` field |
| **Backend event source** | `astream_events(version="v2")` — fine-grained LangChain events | `astream()` + `aget_state()` — coarse graph-level output |
| **Python dependency** | `ag-ui-protocol >= 0.1.15` | None (pure SSE with `sse-starlette`) |
| **Frontend services** | Two: `AgUiService` (transport) + `ChatService` (state) | One: `ChatService` (handles both) |
| **AbortController** | Built into `AgUiService` | Not implemented |
| **Interoperability** | Any AG-UI client can consume the stream | Custom client required |

### When to use which

- **AG-UI**: When you want a standardised protocol, step-by-step visibility, and the ability to swap frontends without changing the backend.
- **Native SSE**: When you want minimal dependencies and a simpler request/response contract.

---

## Gotchas & Troubleshooting

### Empty assistant bubble before text arrives

**Symptom**: No empty bubble flashes — text just appears.

**Explanation**: This is **expected** with AG-UI. Unlike the native approach, the AG-UI `ChatService` does not pre-create a placeholder. The message only appears when `TEXT_MESSAGE_START` arrives from the backend.

### No step labels in the typing indicator

**Symptom**: The typing dots appear but no "Thinking" / "Narrowing search" label shows.

**Cause**: The `STEP_STARTED` event uses the raw LangGraph node name (e.g. `supervisor`). The `ChatComponent.stepLabels` map must include an entry for it. If the node name is missing from the map, the fallback `step.replace(/_/g, ' ')` is used.

**Fix**: Add the missing node name to the `stepLabels` record:
```typescript
private readonly stepLabels: Record<string, string> = {
  supervisor: 'Thinking',
  // add new nodes here
};
```

### Interrupt not detected

**Symptom**: The stream ends normally but no interrupt UI appears.

**Cause**: `astream_events()` does NOT emit interrupts in its event stream. The backend must **explicitly check** for pending interrupts after the stream completes by calling `aget_state(config)`:

```python
# After the astream_events() loop:
state = await self._graph.aget_state(config)
if state and hasattr(state, "tasks"):
    for task in state.tasks:
        if hasattr(task, "interrupts") and task.interrupts:
            return encoder.encode(
                CustomEvent(
                    name="interrupt",
                    value=task.interrupts[0].value,
                )
            )
```

### SSE events arrive all at once

**Symptom**: Tokens don't stream incrementally — the entire response appears at once.

**Cause**: The BFF proxy is buffering the response. See the [BFF Proxy Configuration](#bff-proxy-configuration) section for the `flushHeaders()` fix.

### Multi-byte characters garbled

**Fix**: Always pass `{ stream: true }` to `TextDecoder.decode()`:
```typescript
buffer += decoder.decode(value, { stream: true });
```

### `messageId` mismatch — deltas ignored

**Symptom**: Some tokens are silently dropped during streaming.

**Cause**: The backend resets `message_id` when a step boundary closes and reopens a text message. If the frontend's `streamingMessageId` doesn't match the new ID from `TEXT_MESSAGE_START`, subsequent `TEXT_MESSAGE_CONTENT` events are ignored.

**Fix**: Ensure `onTextStart()` always updates `streamingMessageId` to `event.messageId`.

### AbortController — cancelling in-flight requests

`AgUiService` supports aborting a running stream via `abort()`. This is called automatically in `newThread()` and at the start of each `run()` to prevent duplicate streams. The `AbortError` is caught and silently ignored.

### `uuid` dependency

Install the UUID library:
```bash
npm install uuid
npm install -D @types/uuid
```

---

## Backend Implementation Reference

### `AgUiService` (Python)

The backend service at `backend/app/service/ag_ui_service.py` translates LangGraph's `astream_events(version="v2")` into AG-UI protocol events:

| LangGraph event | AG-UI event(s) |
|----------------|----------------|
| `on_chain_start` (graph node) | `STEP_STARTED` (+ close previous step/message if open) |
| `on_chat_model_stream` (with content) | `TEXT_MESSAGE_START` (once) + `TEXT_MESSAGE_CONTENT` (per chunk) |
| `on_chain_end` (graph node) | `TEXT_MESSAGE_END` (if message open) + `STEP_FINISHED` |
| Post-stream `aget_state()` with interrupt | `CUSTOM` (name="interrupt") |
| Exception | `RUN_ERROR` |

The full stream is bookended by `RUN_STARTED` and `RUN_FINISHED`.

### Route registration

```python
# backend/app/main.py
app.include_router(chat_router, prefix="/api/v1")
# chat_router has prefix="/chat", endpoint POST "/stream"
# → full path: POST /api/v1/chat/stream
```

---

## File Checklist

| File | Purpose |
|------|---------|
| `backend/app/api/routes/ag_ui.py` | FastAPI route: `POST /api/v1/chat/stream` |
| `backend/app/service/ag_ui_service.py` | LangGraph → AG-UI event translation |
| `backend/app/api/deps.py` | Service dependency injection |
| `frontend/client/src/app/core/models/ag-ui.model.ts` | AG-UI event types + `RunAgentInput` |
| `frontend/client/src/app/core/models/chat.model.ts` | `ChatMessage`, `InterruptPayload`, `ChatResponse` |
| `frontend/client/src/app/core/services/ag-ui.service.ts` | SSE transport (fetch + parse + dispatch) |
| `frontend/client/src/app/core/services/chat.service.ts` | Application state (messages, interrupts, resume) |
| `frontend/client/src/app/features/chat/chat.component.ts` | Chat container, step labels, event routing |
| `frontend/client/src/app/features/chat/message/message.component.ts` | Message rendering + interrupt UI |
| `frontend/client/src/app/features/chat/chat-input/chat-input.component.ts` | Text input with enter-to-send |
| `frontend/client/src/environments/environment.ts` | API base URL |
| `frontend/server/src/index.ts` | BFF proxy |
