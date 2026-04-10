import { Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import {
  ChatMessage,
  ChatRequest,
  ChatResumeRequest,
  ChatResponse,
} from '../models/chat.model';
import { environment } from '../../../environments/environment';
import { v4 as uuidv4 } from 'uuid';

@Injectable({ providedIn: 'root' })
export class ChatService {
  messages = signal<ChatMessage[]>([]);
  threadId = signal<string>(uuidv4());
  loading = signal<boolean>(false);
  currentInterrupt = signal<ChatResponse | null>(null);

  private readonly apiUrl = environment.apiBaseUrl;

  constructor(private http: HttpClient) {}

  async sendMessage(content: string): Promise<void> {
    const userMsg: ChatMessage = {
      role: 'user',
      content,
      timestamp: new Date(),
    };
    this.messages.update((msgs) => [...msgs, userMsg]);
    this.loading.set(true);

    const body: ChatRequest = {
      message: content,
      thread_id: this.threadId(),
      user_id: 'anonymous',
    };

    try {
      const resp = await this.http
        .post<ChatResponse>(`${this.apiUrl}/chat`, body)
        .toPromise();

      if (!resp) return;

      this.threadId.set(resp.thread_id || this.threadId());

      if (resp.type === 'interrupt' && resp.interrupt) {
        this.currentInterrupt.set(resp);
        const assistantMsg: ChatMessage = {
          role: 'assistant',
          content:
            resp.interrupt.interrupt_value?.['message']?.toString() ||
            'Please complete the action in the panel.',
          timestamp: new Date(),
          interrupt: resp.interrupt,
        };
        this.messages.update((msgs) => [...msgs, assistantMsg]);
      } else if (resp.type === 'message') {
        const assistantMsg: ChatMessage = {
          role: 'assistant',
          content: resp.content,
          timestamp: new Date(),
        };
        this.messages.update((msgs) => [...msgs, assistantMsg]);
      } else if (resp.type === 'error') {
        const errMsg: ChatMessage = {
          role: 'system',
          content: `Error: ${resp.content}`,
          timestamp: new Date(),
        };
        this.messages.update((msgs) => [...msgs, errMsg]);
      }
    } catch (err: any) {
      const errMsg: ChatMessage = {
        role: 'system',
        content: `Network error: ${err.message || err}`,
        timestamp: new Date(),
      };
      this.messages.update((msgs) => [...msgs, errMsg]);
    } finally {
      this.loading.set(false);
    }
  }

  async resumeWithData(data: Record<string, unknown>): Promise<void> {
    this.loading.set(true);
    this.currentInterrupt.set(null);

    const body: ChatResumeRequest = {
      resume_data: data,
      thread_id: this.threadId(),
      user_id: 'anonymous',
    };

    try {
      const resp = await this.http
        .post<ChatResponse>(`${this.apiUrl}/chat/resume`, body)
        .toPromise();

      if (!resp) return;

      if (resp.type === 'interrupt' && resp.interrupt) {
        this.currentInterrupt.set(resp);
        const assistantMsg: ChatMessage = {
          role: 'assistant',
          content:
            resp.interrupt.interrupt_value?.['message']?.toString() ||
            'Please complete the next step in the panel.',
          timestamp: new Date(),
          interrupt: resp.interrupt,
        };
        this.messages.update((msgs) => [...msgs, assistantMsg]);
      } else if (resp.type === 'message') {
        const assistantMsg: ChatMessage = {
          role: 'assistant',
          content: resp.content,
          timestamp: new Date(),
        };
        this.messages.update((msgs) => [...msgs, assistantMsg]);
      }
    } catch (err: any) {
      const errMsg: ChatMessage = {
        role: 'system',
        content: `Resume error: ${err.message || err}`,
        timestamp: new Date(),
      };
      this.messages.update((msgs) => [...msgs, errMsg]);
    } finally {
      this.loading.set(false);
    }
  }

  newThread(): void {
    this.messages.set([]);
    this.threadId.set(uuidv4());
    this.currentInterrupt.set(null);
  }
}
