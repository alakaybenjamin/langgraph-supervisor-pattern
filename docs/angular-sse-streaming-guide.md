# Angular SSE Streaming Integration Guide

How to connect an Angular frontend to the `POST /api/v1/chat/stream` endpoint using Server-Sent Events (SSE) with the fetch API.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [API Contract](#api-contract)
3. [SSE Wire Format](#sse-wire-format)
4. [TypeScript Interfaces](#typescript-interfaces)
5. [ChatService — Full Implementation](#chatservice--full-implementation)
6. [ChatComponent — Wiring the UI](#chatcomponent--wiring-the-ui)
7. [MessageComponent — Rendering Interrupts](#messagecomponent--rendering-interrupts)
8. [ChatInputComponent — Text Input](#chatinputcomponent--text-input)
9. [BFF Proxy Configuration](#bff-proxy-configuration)
10. [Environment Configuration](#environment-configuration)
11. [Key Concepts Explained](#key-concepts-explained)
12. [Gotchas & Troubleshooting](#gotchas--troubleshooting)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────┐
│  BROWSER  (Angular 19 SPA)                       │
│                                                  │
│  ChatService                                     │
│    ├── sendMessage("hello")                      │
│    │     └── streamRequest({action:"send",...})   │
│    └── resumeWithData({value:"R&D"})             │
│          └── streamRequest({action:"resume",...}) │
│                      │                           │
│           fetch() + ReadableStream               │
│           POST /api/chat/stream                  │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  EXPRESS BFF  (localhost:4200)                    │
│                                                  │
│  /api/*  ──proxy──►  http://localhost:8000/api/v1/*│
│                                                  │
│  SSE passthrough: flushHeaders() on              │
│  content-type: text/event-stream                 │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  FASTAPI BACKEND  (localhost:8000)               │
│                                                  │
│  POST /api/v1/chat/stream                        │
│    → EventSourceResponse (SSE)                   │
│    → LangGraph astream() + aget_state()          │
│                                                  │
│  Events emitted:                                 │
│    event: token   → { "token": "..." }           │
│    event: done    → { "type":"message", ... }    │
│    event: interrupt → { "type":"interrupt", ... } │
│    event: error   → { "type":"error", ... }      │
└──────────────────────────────────────────────────┘
```

### Why SSE instead of WebSockets?

- **One-directional streaming** fits the LLM response pattern (server → client).
- **Standard HTTP** — works through corporate proxies, load balancers, and CDNs without special configuration.
- **POST body** — unlike native `EventSource` (GET-only), we use `fetch()` with a POST body, which lets us send the full request payload on every call.
- **Stateless** — each request is independent. The conversation state lives in the LangGraph checkpoint (PostgreSQL), not in a socket connection.

---

## API Contract

### Endpoint

```
POST /api/v1/chat/stream
Content-Type: application/json
Accept: text/event-stream
```

### Request Body

A single unified request body handles both "send a new message" and "resume from an interrupt":

```json
{
  "action": "send",
  "message": "I want to request access to Clinical Data Products",
  "resume_data": {},
  "thread_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "anonymous"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `action` | `"send" \| "resume"` | `"send"` | `"send"` for new messages, `"resume"` to continue after an interrupt |
| `message` | `string` | `""` | The user's text message (used when `action === "send"`) |
| `resume_data` | `object` | `{}` | Data to resume the graph with (used when `action === "resume"`) |
| `thread_id` | `string` | `""` | UUID identifying the conversation thread. If empty, the backend generates one |
| `user_id` | `string` | `"anonymous"` | Identifies the user |

#### Send example

```json
{
  "action": "send",
  "message": "I want to request access to Clinical Data Products",
  "thread_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "anonymous"
}
```

#### Resume example

```json
{
  "action": "resume",
  "resume_data": { "value": "r_and_d", "facet": "domain" },
  "thread_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "anonymous"
}
```

### Non-Streaming Endpoint (also available)

```
POST /api/v1/chat
Content-Type: application/json
```

Same request body, but returns a single JSON response instead of an SSE stream. Useful for programmatic/API use. The Angular UI uses `/chat/stream` exclusively.

---

## SSE Wire Format

The backend emits [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events) in this format:

```
event: <event-name>\n
data: <json-string>\n
\n
```

Each event is separated by a blank line. The `event:` line names the event type and the `data:` line contains a JSON payload.

### Event Types

#### 1. `token` — Streaming LLM text

Emitted as the LLM generates tokens. Many of these arrive in rapid succession.

```
event: token
data: {"token": "I can help"}

event: token
data: {"token": " you with that"}

event: token
data: {"token": "!"}
```

#### 2. `done` — Stream complete (no interrupt)

Emitted once when the graph finishes without an interrupt. Contains the final `thread_id` so the frontend can track it.

```
event: done
data: {"type": "message", "content": "I can help you with that!", "thread_id": "550e8400-..."}
```

#### 3. `interrupt` — Graph paused, waiting for user input

Emitted when a graph node calls `interrupt()`. The graph is now frozen — the user must interact with the UI and the frontend must call `action: "resume"` with the result.

```
event: interrupt
data: {"type": "interrupt", "interrupt_value": {"type": "facet_selection", "facet": "domain", "message": "What domain are you interested in?", "options": [{"id": "r_and_d", "label": "R&D / Clinical"}, {"id": "commercial", "label": "Commercial"}]}, "thread_id": "550e8400-..."}
```

#### 4. `error` — Something went wrong

```
event: error
data: {"type": "error", "content": "An error occurred: ..."}
```

### Interrupt Types

The `interrupt_value.type` field determines what UI to render:

| `interrupt_value.type` | UI to Render | Resume Payload |
|------------------------|-------------|----------------|
| `facet_selection` | Clickable chip buttons | `{ "value": "r_and_d", "facet": "domain" }` |
| `product_selection` | Product cards with checkboxes | `{ "action": "select", "products": [...] }` |
| `cart_review` | Cart summary with action buttons | `{ "action": "fill_forms" }` |
| `mcp_app` | Opens MCP App in side panel (see Doc 2) | `{ "form_data": "...", "submitted": true }` |
| `confirmation` | Submit / edit / add-more buttons | `{ "confirmed": true, "action": "confirm" }` |

---

## TypeScript Interfaces

Create `core/models/chat.model.ts`:

```typescript
// --- Core message model ---

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  interrupt?: InterruptPayload;  // attached when the message is an interrupt
}

// --- Request body (same for send and resume) ---

export interface ChatRequest {
  action: 'send' | 'resume';
  message?: string;
  resume_data?: Record<string, unknown>;
  thread_id: string;
  user_id: string;
}

// --- Interrupt data attached to a message ---

export interface InterruptPayload {
  type: string;                              // always "interrupt"
  interrupt_value: Record<string, unknown>;  // the graph node's interrupt() argument
  thread_id: string;
}

// --- SSE event payloads ---

export interface SSETokenEvent {
  token: string;
}

export interface SSEDoneEvent {
  type: 'message';
  content: string;
  thread_id: string;
}

export interface SSEInterruptEvent {
  type: 'interrupt';
  interrupt_value: Record<string, unknown>;
  thread_id: string;
}

export interface SSEErrorEvent {
  type: 'error';
  content: string;
}
```

---

## ChatService — Full Implementation

This is the heart of the frontend streaming integration. It lives at `core/services/chat.service.ts`.

### Why `fetch()` instead of Angular's `HttpClient`?

Angular's `HttpClient` buffers the entire response before returning it. For SSE streaming, we need to read the response body **incrementally** as chunks arrive. The native `fetch()` API exposes a `ReadableStream` on `response.body`, which lets us process each chunk as it arrives from the server.

### Complete code

```typescript
import { Injectable, signal } from '@angular/core';
import {
  ChatMessage,
  ChatRequest,
  InterruptPayload,
  SSEDoneEvent,
  SSEInterruptEvent,
  SSETokenEvent,
} from '../models/chat.model';
import { environment } from '../../../environments/environment';
import { v4 as uuidv4 } from 'uuid';

interface InterruptState {
  interrupt: InterruptPayload;
}

@Injectable({ providedIn: 'root' })
export class ChatService {
  // --- Public signals (consumed by components) ---
  messages = signal<ChatMessage[]>([]);
  threadId = signal<string>(uuidv4());
  loading = signal<boolean>(false);
  currentInterrupt = signal<InterruptState | null>(null);

  private readonly apiUrl = environment.apiBaseUrl;

  // === PUBLIC METHODS =====================================================

  /**
   * Send a new user message. Appends it to the message list,
   * then streams the assistant's response.
   */
  async sendMessage(content: string): Promise<void> {
    const userMsg: ChatMessage = {
      role: 'user',
      content,
      timestamp: new Date(),
    };
    this.messages.update((msgs) => [...msgs, userMsg]);

    await this.streamRequest({
      action: 'send',
      message: content,
      thread_id: this.threadId(),
      user_id: 'anonymous',
    });
  }

  /**
   * Resume from an interrupt. Clears the current interrupt state
   * and sends the resume data to the backend.
   */
  async resumeWithData(data: Record<string, unknown>): Promise<void> {
    this.currentInterrupt.set(null);

    await this.streamRequest({
      action: 'resume',
      resume_data: data,
      thread_id: this.threadId(),
      user_id: 'anonymous',
    });
  }

  /**
   * Start a fresh conversation.
   */
  newThread(): void {
    this.messages.set([]);
    this.threadId.set(uuidv4());
    this.currentInterrupt.set(null);
  }

  // === PRIVATE: SSE STREAM CONSUMER =======================================

  /**
   * Core streaming method. Sends a POST request and reads the SSE response
   * body as a ReadableStream, parsing events incrementally.
   *
   * Flow:
   *   1. Add empty placeholder assistant message (shows typing indicator area)
   *   2. POST to /chat/stream with fetch()
   *   3. Read response.body with a ReadableStream reader
   *   4. Parse SSE lines: "event: <name>" + "data: <json>"
   *   5. Dispatch to handleSSEEvent() for each complete event
   *   6. On stream end, flush any remaining buffer
   */
  private async streamRequest(body: ChatRequest): Promise<void> {
    this.loading.set(true);

    // Step 1: Add an empty assistant message as a placeholder.
    // Token events will append to this message incrementally.
    const placeholderMsg: ChatMessage = {
      role: 'assistant',
      content: '',
      timestamp: new Date(),
    };
    this.messages.update((msgs) => [...msgs, placeholderMsg]);

    try {
      // Step 2: POST to the streaming endpoint.
      // We use fetch() instead of HttpClient because HttpClient
      // buffers the full response — we need incremental streaming.
      const response = await fetch(`${this.apiUrl}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!response.ok || !response.body) {
        this.updateLastAssistantMessage(`Error: HTTP ${response.status}`);
        return;
      }

      // Step 3: Get a reader for the response stream.
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      // Step 4: Read chunks until the stream ends.
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        // Decode the binary chunk to text and append to buffer.
        // The { stream: true } option handles multi-byte characters
        // that might be split across chunks.
        buffer += decoder.decode(value, { stream: true });

        // Split on newlines. The last element might be incomplete,
        // so we keep it in the buffer for the next iteration.
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        // Step 5: Parse SSE protocol.
        // SSE format: "event: <name>\ndata: <json>\n\n"
        let eventName = '';
        for (const line of lines) {
          if (line.startsWith('event:')) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith('data:') && eventName) {
            const jsonStr = line.slice(5).trim();
            this.handleSSEEvent(eventName, jsonStr);
            eventName = '';
          }
        }
      }

      // Step 6: Process any remaining data in the buffer
      // after the stream closes.
      if (buffer.trim()) {
        const lines = buffer.split('\n');
        let eventName = '';
        for (const line of lines) {
          if (line.startsWith('event:')) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith('data:') && eventName) {
            this.handleSSEEvent(eventName, line.slice(5).trim());
            eventName = '';
          }
        }
      }
    } catch (err: any) {
      this.updateLastAssistantMessage(`Network error: ${err.message || err}`);
    } finally {
      this.loading.set(false);
    }
  }

  // === PRIVATE: EVENT HANDLERS ============================================

  /**
   * Route each SSE event to the appropriate handler.
   */
  private handleSSEEvent(eventName: string, jsonStr: string): void {
    try {
      const data = JSON.parse(jsonStr);

      switch (eventName) {
        case 'token': {
          // Append this token to the last assistant message.
          const tokenData = data as SSETokenEvent;
          this.appendToLastAssistantMessage(tokenData.token);
          break;
        }
        case 'done': {
          // Stream finished normally. Sync the thread_id.
          const doneData = data as SSEDoneEvent;
          this.threadId.set(doneData.thread_id || this.threadId());
          break;
        }
        case 'interrupt': {
          // Graph paused — store the interrupt and update the message.
          const interruptData = data as SSEInterruptEvent;
          this.threadId.set(interruptData.thread_id || this.threadId());
          const payload: InterruptPayload = {
            type: interruptData.type,
            interrupt_value: interruptData.interrupt_value,
            thread_id: interruptData.thread_id,
          };
          this.currentInterrupt.set({ interrupt: payload });

          // Use the interrupt's message field as the bubble text,
          // or fall back to a generic prompt.
          const msg =
            interruptData.interrupt_value?.['message']?.toString() ||
            'Please complete the action in the panel.';
          this.updateLastAssistantMessage(msg, payload);
          break;
        }
        case 'error': {
          this.updateLastAssistantMessage(
            `Error: ${data.content || 'Unknown error'}`
          );
          break;
        }
      }
    } catch {
      // Malformed JSON from the stream — skip silently.
    }
  }

  // === PRIVATE: MESSAGE MUTATION HELPERS ===================================

  /**
   * Append a token string to the last assistant message's content.
   * This is called many times in rapid succession during streaming.
   *
   * Uses immutable update: creates a new array with a new object
   * for the last element. Angular's signal change detection picks
   * this up and re-renders the message bubble.
   */
  private appendToLastAssistantMessage(token: string): void {
    this.messages.update((msgs) => {
      const updated = [...msgs];
      const last = updated[updated.length - 1];
      if (last?.role === 'assistant') {
        updated[updated.length - 1] = {
          ...last,
          content: last.content + token,
        };
      }
      return updated;
    });
  }

  /**
   * Replace the last assistant message's content entirely.
   * Used for interrupt messages and error messages.
   * Optionally attaches an InterruptPayload, which tells the
   * MessageComponent to render interactive UI (chips, cards, etc.).
   */
  private updateLastAssistantMessage(
    content: string,
    interrupt?: InterruptPayload
  ): void {
    this.messages.update((msgs) => {
      const updated = [...msgs];
      const last = updated[updated.length - 1];
      if (last?.role === 'assistant') {
        updated[updated.length - 1] = { ...last, content, interrupt };
      }
      return updated;
    });
  }
}
```

### How signals drive the UI

```
messages signal ──────►  @for loop in ChatComponent ──► MessageComponent[]
loading signal  ──────►  typing indicator / input disabled
currentInterrupt ─────►  McpPanelComponent (effect watches this)
threadId signal  ─────►  included in every request body
```

Every signal update triggers Angular's change detection for any component that reads it. No manual `detectChanges()` or zone tricks needed.

---

## ChatComponent — Wiring the UI

This is the top-level chat container. It renders the message list, the input box, and handles user actions that should resume the graph.

Create `features/chat/chat.component.ts`:

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

        <!-- Render every message in the conversation -->
        @for (msg of chatService.messages(); track $index) {
          <app-message
            [msg]="msg"
            (facetSelected)="onFacetSelected($event)"
            (productSelected)="onProductSelected($event)"
            (cartAction)="onCartAction($event)"
            (confirmed)="onConfirmed($event)"
          />
        }

        <!-- Typing indicator while waiting for the stream -->
        @if (chatService.loading()) {
          <div class="typing-indicator">
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
   * When the user types a message while an interrupt is active,
   * decide whether to resume the graph or send a new message.
   */
  onSend(message: string): void {
    const interrupt = this.chatService.currentInterrupt();
    if (interrupt?.interrupt) {
      const interruptType = interrupt.interrupt.interrupt_value?.['type'];

      // During an active facet_selection interrupt, typing "refine"
      // resets filters. Otherwise, send normally.
      if (interruptType === 'facet_selection') {
        const lower = message.toLowerCase();
        if (['refine', 'go back', 'start over'].some(p => lower.includes(p))) {
          this.chatService.resumeWithData({ value: 'all' });
          return;
        }
      }
    }
    this.chatService.sendMessage(message);
  }

  /**
   * User clicked a facet chip (e.g. "R&D / Clinical").
   * Resume the graph with { value: "r_and_d", facet: "domain" }.
   */
  onFacetSelected(data: Record<string, unknown>): void {
    this.chatService.resumeWithData(data);
  }

  /**
   * User confirmed product selection.
   * Resume with { action: "select", products: [...] }.
   */
  onProductSelected(data: Record<string, unknown>): void {
    this.chatService.resumeWithData(data);
  }

  /**
   * User clicked a cart action button.
   * Resume with { action: "fill_forms" } or { action: "add_more" }.
   */
  onCartAction(data: Record<string, unknown>): void {
    this.chatService.resumeWithData(data);
  }

  /**
   * User confirmed or rejected the final submission.
   * Resume with { confirmed: true/false, action: "confirm"/"edit" }.
   */
  onConfirmed(yes: boolean): void {
    this.chatService.resumeWithData({
      confirmed: yes,
      action: yes ? 'confirm' : 'edit',
    });
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
  2. Calls streamRequest({ action: "resume", resume_data: data, thread_id, ... })
        │
        ▼
POST /api/chat/stream  { action: "resume", resume_data: {...}, thread_id: "..." }
        │
        ▼
Backend: graph.ainvoke(Command(resume=resume_data), config)
  → interrupt() returns resume_data to the node
  → node processes it, graph continues
  → next event arrives (token / interrupt / done)
```

---

## MessageComponent — Rendering Interrupts

Each `ChatMessage` might carry an `interrupt` payload. The `MessageComponent` inspects `msg.interrupt.interrupt_value.type` to decide what interactive UI to show below the message text.

Create `features/chat/message/message.component.ts`:

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
        {{ msg.role === 'user' ? 'U' : 'A' }}
      </div>
      <div class="bubble">
        <!-- Message text (supports **bold** and newlines) -->
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

        <!-- Badge shown after user has interacted -->
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

  resolved = false;
  selectedProducts: any[] = [];

  // --- Accessors that extract typed data from the interrupt payload ---

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

  // --- User interaction handlers ---

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
SSE event: interrupt
  │
  ▼
handleSSEEvent("interrupt", jsonStr)
  │
  ├── Sets currentInterrupt signal (for McpPanelComponent)
  │
  └── Calls updateLastAssistantMessage(msg, payload)
        │
        └── msg.interrupt = {
              type: "interrupt",
              interrupt_value: {
                type: "facet_selection",     ◄── This drives the template
                facet: "domain",
                message: "What domain?",
                options: [                   ◄── These become chips
                  { id: "r_and_d", label: "R&D / Clinical" },
                  { id: "commercial", label: "Commercial" },
                  ...
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

A simple text input with enter-to-send. Create `features/chat/chat-input/chat-input.component.ts`:

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

The Angular app is served by an Express BFF that proxies API and MCP requests. SSE requires special handling — the proxy must flush headers immediately instead of buffering.

`frontend/server/src/index.ts`:

```typescript
import express from 'express';
import { createProxyMiddleware } from 'http-proxy-middleware';

const app = express();
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

app.use(
  '/api',
  createProxyMiddleware({
    target: BACKEND_URL,
    changeOrigin: true,
    pathRewrite: (_path) => `/api/v1${_path}`,
    on: {
      // CRITICAL for SSE: flush headers immediately when
      // the backend responds with text/event-stream.
      // Without this, the proxy buffers the entire response
      // and the frontend sees nothing until the stream ends.
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

### URL mapping

| Browser request | BFF proxy | Backend |
|----------------|-----------|---------|
| `POST /api/chat/stream` | rewrites path | `POST /api/v1/chat/stream` |
| `POST /api/chat` | rewrites path | `POST /api/v1/chat` |
| `POST /mcp/search-app` | path preserved | `POST /mcp/search-app` |

---

## Environment Configuration

`environments/environment.ts`:

```typescript
export const environment = {
  production: false,
  apiBaseUrl: '/api',        // proxied to http://localhost:8000/api/v1
  mcpBaseUrl: '/mcp/question-form',
};
```

The `apiBaseUrl` is `/api` (relative). The BFF proxy handles the rewrite to `/api/v1`. In production, this would point to the actual backend URL.

---

## Key Concepts Explained

### 1. Thread ID — Conversation Identity

Every conversation has a UUID `thread_id`. The LangGraph backend uses this to:
- **Checkpoint state** to PostgreSQL after every node execution
- **Resume** from exactly where it left off when the frontend sends `action: "resume"`

The frontend generates a new `thread_id` (via `uuidv4()`) when starting a new conversation. The backend may also generate one if `thread_id` is empty.

### 2. Signals — Reactive State

Angular signals are the reactive primitive used throughout. When a signal's value changes, any component template that reads it re-renders automatically.

```typescript
// In ChatService:
messages = signal<ChatMessage[]>([]);     // the message list
loading = signal<boolean>(false);          // show/hide typing indicator
currentInterrupt = signal<InterruptState | null>(null);  // active interrupt

// In a template:
@for (msg of chatService.messages(); track $index) { ... }
// ^ Angular re-evaluates this whenever messages signal changes
```

### 3. The Placeholder Pattern

Before streaming starts, we add an empty assistant message:

```typescript
const placeholderMsg: ChatMessage = {
  role: 'assistant',
  content: '',            // empty — will be filled by tokens
  timestamp: new Date(),
};
this.messages.update((msgs) => [...msgs, placeholderMsg]);
```

As `token` events arrive, we append to this message's content. The user sees text appearing character by character, just like ChatGPT.

If an `interrupt` event arrives instead of tokens, we replace the empty content with the interrupt's message text and attach the interrupt payload — this triggers the interactive UI (chips, cards, etc.).

### 4. Immutable Updates

Signal-based change detection relies on **reference equality**. To trigger a re-render, you must create a new array/object:

```typescript
// CORRECT — new array, new last element
this.messages.update((msgs) => {
  const updated = [...msgs];                         // new array
  const last = updated[updated.length - 1];
  updated[updated.length - 1] = { ...last, content: last.content + token }; // new object
  return updated;
});

// WRONG — mutating in place, signal won't detect the change
this.messages.update((msgs) => {
  msgs[msgs.length - 1].content += token;  // same reference!
  return msgs;                              // same array reference!
});
```

### 5. The Interrupt Lifecycle

```
1. Backend graph node calls interrupt({ type: "facet_selection", ... })
2. Graph freezes, state saved to PostgreSQL
3. Backend emits SSE event: interrupt with the interrupt value
4. Frontend ChatService:
   a. Sets currentInterrupt signal (used by McpPanelComponent for mcp_app type)
   b. Updates last assistant message with content + interrupt payload
5. MessageComponent renders interactive UI based on interrupt_value.type
6. User clicks a chip / selects products / confirms
7. Component emits event → ChatComponent calls chatService.resumeWithData(data)
8. ChatService POSTs { action: "resume", resume_data: data, thread_id }
9. Backend: graph.ainvoke(Command(resume=data), config)
   → interrupt() returns data → node processes → graph continues
10. New stream begins → tokens / next interrupt / done
```

---

## Gotchas & Troubleshooting

### Empty assistant bubble (no content, no chips)

**Symptom**: The assistant message appears with just the timestamp and no content.

**Cause**: `astream()` does NOT emit `__interrupt__` in its values stream. After the stream ends, the backend must call `aget_state(config)` and check `state.tasks[*].interrupts` for pending interrupts. If this check is missing, the stream ends without emitting anything.

**Backend fix** (already implemented):
```python
# After the astream() loop:
state = await self._graph.aget_state(config)
if state.tasks:
    for task in state.tasks:
        if task.interrupts:
            interrupt_val = task.interrupts[0].value
            yield {"event": "interrupt", "data": {...}}
            return
```

### SSE events arrive all at once

**Symptom**: Tokens don't stream incrementally — the entire response appears at once after a delay.

**Cause**: The BFF proxy is buffering the response. Ensure `flushHeaders()` is called when the content type is `text/event-stream`:

```typescript
on: {
  proxyRes: (proxyRes, _req, res) => {
    const ct = proxyRes.headers['content-type'] || '';
    if (ct.includes('text/event-stream')) {
      (res as any).flushHeaders?.();
    }
  },
},
```

### Multi-byte characters garbled

**Symptom**: Non-ASCII characters (CJK, emoji) appear as `?` or broken characters.

**Fix**: Always pass `{ stream: true }` to `TextDecoder.decode()`:
```typescript
buffer += decoder.decode(value, { stream: true });
```

### Thread ID mismatch after resume

**Symptom**: Resume doesn't work — the backend starts a new conversation.

**Cause**: The `thread_id` in the resume request doesn't match the one from the original conversation. Always use the `thread_id` returned in the `done` or `interrupt` event.

### `uuid` dependency

Install the UUID library:
```bash
npm install uuid
npm install -D @types/uuid
```

---

## File Checklist

| File | Purpose |
|------|---------|
| `core/models/chat.model.ts` | All TypeScript interfaces |
| `core/services/chat.service.ts` | SSE consumer, message state, resume |
| `features/chat/chat.component.ts` | Message list, input, event routing |
| `features/chat/message/message.component.ts` | Renders messages + interrupt UI |
| `features/chat/chat-input/chat-input.component.ts` | Text input with enter-to-send |
| `environments/environment.ts` | API base URL |
| `../server/src/index.ts` | BFF proxy with SSE flush |
