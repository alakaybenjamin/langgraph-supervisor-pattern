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
  /** Name of the LangGraph node currently executing. */
  currentStep = signal<string | null>(null);
  /** True while a run is in flight. */
  running = signal<boolean>(false);

  private readonly endpoint = `${environment.apiBaseUrl}/chat/stream`;
  private abortController: AbortController | null = null;

  /**
   * POST a RunAgentInput to the AG-UI endpoint and parse the SSE stream,
   * dispatching each event to {@link onEvent}.
   */
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

  // ---------------------------------------------------------------------------
  // SSE parsing
  // ---------------------------------------------------------------------------

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
