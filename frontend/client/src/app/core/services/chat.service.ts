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

  // ---------------------------------------------------------------------------
  // AG-UI event dispatcher
  // ---------------------------------------------------------------------------

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
