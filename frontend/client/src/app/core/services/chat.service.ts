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
  messages = signal<ChatMessage[]>([]);
  threadId = signal<string>(uuidv4());
  loading = signal<boolean>(false);
  currentInterrupt = signal<InterruptState | null>(null);

  private readonly apiUrl = environment.apiBaseUrl;

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

  async resumeWithData(data: Record<string, unknown>): Promise<void> {
    this.currentInterrupt.set(null);

    await this.streamRequest({
      action: 'resume',
      resume_data: data,
      thread_id: this.threadId(),
      user_id: 'anonymous',
    });
  }

  newThread(): void {
    this.messages.set([]);
    this.threadId.set(uuidv4());
    this.currentInterrupt.set(null);
  }

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

  private handleSSEEvent(eventName: string, jsonStr: string): void {
    try {
      const data = JSON.parse(jsonStr);

      switch (eventName) {
        case 'token': {
          const tokenData = data as SSETokenEvent;
          this.appendToLastAssistantMessage(tokenData.token);
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
          const payload: InterruptPayload = {
            type: interruptData.type,
            interrupt_value: interruptData.interrupt_value,
            thread_id: interruptData.thread_id,
          };
          this.currentInterrupt.set({ interrupt: payload });

          const msg =
            interruptData.interrupt_value?.['message']?.toString() ||
            'Please complete the action in the panel.';
          this.setInterruptMessage(msg, payload);
          break;
        }
        case 'error': {
          this.updateLastAssistantMessage(`Error: ${data.content || 'Unknown error'}`);
          break;
        }
      }
    } catch {
      // malformed JSON — skip
    }
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

  private updateLastAssistantMessage(content: string, interrupt?: InterruptPayload): void {
    this.messages.update((msgs) => {
      const updated = [...msgs];
      const last = updated[updated.length - 1];
      if (last?.role === 'assistant') {
        updated[updated.length - 1] = { ...last, content, interrupt };
      }
      return updated;
    });
  }

  private setInterruptMessage(content: string, interrupt: InterruptPayload): void {
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
