import { Injectable, Signal, signal } from '@angular/core';
import type { A2uiClientAction } from '@a2ui/web_core/v0_9';
import {
  ChatMessage,
  ChatRequest,
  INTERRUPT_REQUIRED_FIELDS,
  InterruptPayload,
  InterruptValue,
  SSEDoneEvent,
  SSEInterruptEvent,
  SSETokenEvent,
  StreamSubmitInput,
  hasInterruptType,
} from '../models/chat.model';
import { environment } from '../../../environments/environment';
import { v4 as uuidv4 } from 'uuid';

/**
 * A `useStream`-shaped surface over the backend LangGraph stream endpoint,
 * modeled on the LangChain docs pattern for frontends. All callers should
 * drive the conversation through this object:
 *
 *   - {@link StreamApi.submit} — send a user message or resume with data
 *   - {@link StreamApi.switchThread} — pass `null` to start a new thread
 *   - {@link StreamApi.messages} / {@link StreamApi.isLoading} /
 *     {@link StreamApi.currentInterrupt} — reactive signals to render from
 */
export interface StreamApi {
  readonly messages: Signal<ChatMessage[]>;
  readonly isLoading: Signal<boolean>;
  readonly currentInterrupt: Signal<InterruptPayload | null>;
  readonly threadId: Signal<string>;

  submit(input: StreamSubmitInput): Promise<void>;
  switchThread(threadId: string | null): void;
  appendUserText(text: string): void;
}

@Injectable({ providedIn: 'root' })
export class ChatService {
  readonly messages = signal<ChatMessage[]>([]);
  readonly threadId = signal<string>(uuidv4());
  readonly loading = signal<boolean>(false);
  readonly currentInterrupt = signal<InterruptPayload | null>(null);

  private readonly apiUrl = environment.apiBaseUrl;

  // --------------------------------------------------------------------
  // `useStream`-shaped public API
  // --------------------------------------------------------------------

  /** Primary surface — treat this as the `useStream()` return value. */
  readonly stream: StreamApi = {
    messages: this.messages,
    isLoading: this.loading,
    currentInterrupt: this.currentInterrupt,
    threadId: this.threadId,
    submit: (input) => this.submit(input),
    switchThread: (id) => this.switchThread(id),
    appendUserText: (text) => this.appendUserText(text),
  };

  /**
   * Submit either fresh human messages or a resume payload for the current
   * interrupt. Exactly one of `messages`/`resume` is expected; if both are
   * provided, messages are appended to the transcript first, then the
   * resume is dispatched.
   */
  async submit(input: StreamSubmitInput): Promise<void> {
    const { messages, resume } = input;

    if (messages?.length) {
      this.messages.update((msgs) => [
        ...msgs,
        ...messages.map((m) => ({
          role: 'user' as const,
          content: m.content,
          timestamp: new Date(),
        })),
      ]);
    }

    if (resume) {
      this.currentInterrupt.set(null);
      await this.streamRequest({
        action: 'resume',
        resume_data: resume,
        thread_id: this.threadId(),
        user_id: 'anonymous',
      });
      return;
    }

    const lastMsg = messages?.[messages.length - 1]?.content;
    if (lastMsg !== undefined) {
      await this.streamRequest({
        action: 'send',
        message: lastMsg,
        thread_id: this.threadId(),
        user_id: 'anonymous',
      });
    }
  }

  /** Pass `null` to start a fresh thread; pass an id to adopt it. */
  switchThread(threadId: string | null): void {
    this.messages.set([]);
    this.currentInterrupt.set(null);
    this.threadId.set(threadId ?? uuidv4());
  }

  /**
   * Append a user-authored line to the transcript without issuing a
   * network request. Used when the caller wants to show the user's typed
   * text alongside a `resume` submit.
   */
  appendUserText(text: string): void {
    this.messages.update((msgs) => [
      ...msgs,
      { role: 'user', content: text, timestamp: new Date() },
    ]);
  }

  // --------------------------------------------------------------------
  // Back-compat shims (thin delegates so existing callers keep working)
  // --------------------------------------------------------------------

  /** @deprecated Use `stream.submit({ messages: [...] })`. */
  async sendMessage(content: string): Promise<void> {
    await this.submit({ messages: [{ type: 'human', content }] });
  }

  /** @deprecated Use `stream.submit({ resume: data })`. */
  async resumeWithData(data: Record<string, unknown>): Promise<void> {
    await this.submit({ resume: data });
  }

  /** @deprecated Use `stream.switchThread(null)`. */
  newThread(): void {
    this.switchThread(null);
  }

  // --------------------------------------------------------------------
  // A2UI action bridge
  // --------------------------------------------------------------------

  /**
   * Translate an A2UI client action into the legacy ``resume_data`` shape
   * that the LangGraph subgraph's ``_apply_structured_answer`` expects,
   * and submit it. This is the single place where A2UI-authored events
   * meet the existing resume-routing contract — keep it side-effect free
   * aside from the final ``stream.submit`` so multi-phase rollouts stay
   * reversible behind the backend feature flag.
   *
   * The correct translation for any given action is derived from the
   * current interrupt's ``resume_hint`` (set by the backend builder),
   * not from the action name alone, so that a single event name like
   * ``facet.select`` can participate in any facet question.
   */
  handleA2uiAction(action: A2uiClientAction): void {
    const interrupt = this.currentInterrupt()?.interrupt_value;
    if (!interrupt || !hasInterruptType(interrupt, 'a2ui')) {
      console.warn(
        '[ChatService] A2UI action received with no matching interrupt:',
        action,
      );
      return;
    }

    const hint = interrupt.resume_hint;
    switch (hint.ui_type) {
      case 'facet_selection': {
        const ctx = action.context ?? {};
        const value = typeof ctx['value'] === 'string' ? ctx['value'] : undefined;
        if (!value) {
          console.warn(
            '[ChatService] A2UI facet.select action missing context.value:',
            action,
          );
          return;
        }
        void this.submit({
          resume: { facet: hint.facet, value },
        });
        return;
      }
      case 'product_selection': {
        // The ProductPicker fires four events; only three are
        // user-actionable. ``product.toggle`` is informational and the
        // adapter intentionally ignores it — selection state lives in
        // the renderer until the user hits the primary button.
        const eventName = action.name;
        const ctx = action.context ?? {};
        switch (eventName) {
          case 'product.confirm': {
            const products = Array.isArray(ctx['products'])
              ? (ctx['products'] as Record<string, unknown>[])
              : [];
            void this.submit({
              resume: { action: 'select', products },
            });
            return;
          }
          case 'product.open_search':
            void this.submit({ resume: { action: 'open_search' } });
            return;
          case 'product.refine':
            void this.submit({ resume: { action: 'refine_filters' } });
            return;
          case 'product.toggle':
            return;
          default:
            console.warn(
              '[ChatService] Unhandled A2UI product event:',
              eventName,
              action,
            );
            return;
        }
      }
    }
  }

  // --------------------------------------------------------------------
  // SSE plumbing
  // --------------------------------------------------------------------

  private async streamRequest(body: ChatRequest): Promise<void> {
    this.loading.set(true);

    const placeholderMsg: ChatMessage = {
      role: 'assistant',
      content: '',
      timestamp: new Date(),
    };
    this.messages.update((msgs) => [...msgs, placeholderMsg]);

    try {
      const response = await fetch(`${this.apiUrl}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!response.ok || !response.body) {
        this.updateLastAssistantMessage(`Error: HTTP ${response.status}`);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        this.processSSELines(lines);
      }

      if (buffer.trim()) {
        this.processSSELines(buffer.split('\n'));
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      this.updateLastAssistantMessage(`Network error: ${msg}`);
    } finally {
      this.loading.set(false);
    }
  }

  private processSSELines(lines: string[]): void {
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

  private handleSSEEvent(eventName: string, jsonStr: string): void {
    let data: unknown;
    try {
      data = JSON.parse(jsonStr);
    } catch {
      return;
    }

    switch (eventName) {
      case 'token': {
        const { token } = data as SSETokenEvent;
        this.appendToLastAssistantMessage(token);
        break;
      }
      case 'done': {
        const doneData = data as SSEDoneEvent;
        this.threadId.set(doneData.thread_id || this.threadId());
        if (doneData.content) {
          this.updateLastAssistantMessage(doneData.content);
        }
        break;
      }
      case 'interrupt': {
        const interruptData = data as SSEInterruptEvent;
        this.threadId.set(interruptData.thread_id || this.threadId());

        const validated = this.validateInterruptValue(
          interruptData.interrupt_value,
        );

        if (!validated) {
          // Payload failed required-field validation — log, fall back to
          // a plain assistant bubble so the run doesn't visibly hang.
          console.warn(
            '[ChatService] Dropped malformed interrupt payload:',
            interruptData.interrupt_value,
          );
          this.updateLastAssistantMessage(
            'The assistant sent an incomplete prompt. Please try again.',
          );
          break;
        }

        const payload: InterruptPayload = {
          interrupt_value: validated,
          thread_id: interruptData.thread_id,
        };
        this.currentInterrupt.set(payload);

        const msg = validated.message?.toString()
          || 'Please complete the action in the panel.';
        this.setInterruptMessage(msg, payload);
        break;
      }
      case 'error': {
        const errContent = (data as { content?: unknown })?.content;
        this.updateLastAssistantMessage(
          `Error: ${typeof errContent === 'string' ? errContent : 'Unknown error'}`,
        );
        break;
      }
    }
  }

  /**
   * Validate an interrupt payload against `INTERRUPT_REQUIRED_FIELDS`.
   * Returns the typed value if valid, otherwise `null`.
   *
   * Mirrors the LangChain docs guidance: validate required fields before
   * rendering so partial / malformed structured output never reaches the
   * UI as a broken widget.
   */
  private validateInterruptValue(value: unknown): InterruptValue | null {
    if (!value || typeof value !== 'object') return null;
    const v = value as { type?: unknown };
    const type = v.type;
    if (typeof type !== 'string' || !(type in INTERRUPT_REQUIRED_FIELDS)) {
      return null;
    }
    const required =
      INTERRUPT_REQUIRED_FIELDS[type as keyof typeof INTERRUPT_REQUIRED_FIELDS];
    const rec = v as Record<string, unknown>;
    for (const field of required) {
      if (rec[field as string] === undefined) {
        console.warn(
          `[ChatService] Interrupt of type "${type}" missing required field "${String(field)}"`,
        );
        return null;
      }
    }
    return value as InterruptValue;
  }

  private appendToLastAssistantMessage(token: string): void {
    this.messages.update((msgs) => {
      const updated = [...msgs];
      const last = updated[updated.length - 1];
      if (last?.role === 'assistant') {
        updated[updated.length - 1] = { ...last, content: last.content + token };
      }
      return updated;
    });
  }

  private updateLastAssistantMessage(
    content: string,
    interrupt?: InterruptPayload,
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

  private setInterruptMessage(
    content: string,
    interrupt: InterruptPayload,
  ): void {
    this.messages.update((msgs) => {
      const updated = [...msgs];
      const last = updated[updated.length - 1];

      // If a streamed answer already exists in the current assistant message,
      // keep it and append a fresh assistant bubble for the interrupt prompt.
      if (last?.role === 'assistant' && last.content.trim()) {
        updated.push({
          role: 'assistant',
          content,
          interrupt,
          timestamp: new Date(),
        });
        return updated;
      }

      if (last?.role === 'assistant') {
        updated[updated.length - 1] = { ...last, content, interrupt };
      } else {
        updated.push({
          role: 'assistant',
          content,
          interrupt,
          timestamp: new Date(),
        });
      }
      return updated;
    });
  }
}
