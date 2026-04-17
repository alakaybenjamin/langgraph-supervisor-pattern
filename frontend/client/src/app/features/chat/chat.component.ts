import {
  Component,
  ElementRef,
  ViewChild,
  AfterViewChecked,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatService } from '../../core/services/chat.service';
import { hasInterruptType } from '../../core/models/chat.model';
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
        <button class="new-thread-btn" (click)="stream.switchThread(null)">
          + New Chat
        </button>
      </div>

      <div class="messages-area" #messagesArea>
        @if (stream.messages().length === 0) {
          <div class="empty-state">
            <div class="empty-icon">&#128172;</div>
            <h3>Welcome to Data Governance</h3>
            <p>I can help you with:</p>
            <ul>
              <li>Request access to data products</li>
              <li>Answer questions about data governance</li>
              <li>Check the status of your requests</li>
            </ul>
          </div>
        }
        @for (msg of stream.messages(); track $index) {
          <app-message
            [msg]="msg"
            (productSelected)="onProductSelected($event)"
            (facetSelected)="onFacetSelected($event)"
            (cartAction)="onCartAction($event)"
            (openSearchPanel)="onOpenSearch()"
            (refineSearch)="onRefineSearch()"
          />
        }
        @if (stream.isLoading()) {
          <div class="typing-indicator">
            <div class="dot"></div>
            <div class="dot"></div>
            <div class="dot"></div>
          </div>
        }
      </div>

      <app-chat-input
        [disabled]="stream.isLoading()"
        (messageSent)="onSend($event)"
      />
    </div>
  `,
  styles: [
    `
      .chat-container {
        display: flex;
        flex-direction: column;
        height: 100%;
        background: #fafbfc;
      }

      .chat-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 24px;
        border-bottom: 1px solid #e2e8f0;
        background: white;

        h2 {
          margin: 0;
          font-size: 18px;
          font-weight: 600;
          color: #1e293b;
        }
      }

      .new-thread-btn {
        padding: 8px 16px;
        background: transparent;
        color: #4f46e5;
        border: 1px solid #4f46e5;
        border-radius: 8px;
        cursor: pointer;
        font-size: 13px;
        font-weight: 500;
        transition: all 0.2s;

        &:hover {
          background: #4f46e5;
          color: white;
        }
      }

      .messages-area {
        flex: 1;
        overflow-y: auto;
        padding: 24px;
      }

      .empty-state {
        text-align: center;
        padding: 60px 20px;
        color: #64748b;

        .empty-icon {
          font-size: 48px;
          margin-bottom: 16px;
        }

        h3 {
          margin: 0 0 8px;
          color: #1e293b;
        }

        ul {
          list-style: none;
          padding: 0;
          margin: 16px 0 0;

          li {
            padding: 8px;
            margin: 4px 0;
            background: white;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
          }
        }
      }

      .typing-indicator {
        display: flex;
        gap: 6px;
        padding: 12px 16px;
        margin-left: 48px;

        .dot {
          width: 8px;
          height: 8px;
          background: #94a3b8;
          border-radius: 50%;
          animation: bounce 1.4s infinite ease-in-out;

          &:nth-child(2) {
            animation-delay: 0.2s;
          }
          &:nth-child(3) {
            animation-delay: 0.4s;
          }
        }
      }

      @keyframes bounce {
        0%,
        80%,
        100% {
          transform: scale(0.6);
        }
        40% {
          transform: scale(1);
        }
      }
    `,
  ],
})
export class ChatComponent implements AfterViewChecked {
  private readonly chatService = inject(ChatService);
  readonly stream = this.chatService.stream;

  @ViewChild('messagesArea') private messagesArea!: ElementRef;

  ngAfterViewChecked(): void {
    this.scrollToBottom();
  }

  onSend(message: string): void {
    const interrupt = this.stream.currentInterrupt();
    if (interrupt) {
      const value = interrupt.interrupt_value;
      const lower = message.toLowerCase();

      if (hasInterruptType(value, 'mcp_app')) {
        this.submitUserTextAndResume(message, {
          action: 'user_message',
          text: message,
        });
        return;
      }

      const searchIntent = this.matchesIntent(lower, [
        'open search', 'search panel', 'advanced search',
      ]);
      const refineIntent = this.matchesIntent(lower, [
        'refine', 'change filter', 'different filter', 'try again',
        'go back', 'back to search', 'search again', 'start over',
        'different domain', 'different type',
      ]);
      const addMoreIntent = this.matchesIntent(lower, [
        'add more', 'add another', 'forgot to add', 'one more product',
        'more products', 'another product', 'another data product',
        'need to add', 'want to add', 'also need', 'missed a product',
      ]);

      if (hasInterruptType(value, 'product_selection')) {
        if (searchIntent) {
          this.submitUserTextAndResume(message, { action: 'open_search' });
          return;
        }
        if (refineIntent || addMoreIntent) {
          this.submitUserTextAndResume(message, { action: 'refine_filters' });
          return;
        }
      }

      // For facet_selection, free-text is forwarded to the backend router which
      // classifies it as faq/nav/user_text. Do NOT emit a structured facet
      // answer here — that requires the user to click a chip.
      this.submitUserTextAndResume(message, {
        action: 'user_message',
        text: message,
      });
      return;
    }
    this.stream.submit({ messages: [{ type: 'human', content: message }] });
  }

  private submitUserTextAndResume(
    text: string,
    data: Record<string, unknown>,
  ): void {
    this.stream.appendUserText(text);
    this.stream.submit({ resume: data });
  }

  private matchesIntent(text: string, patterns: string[]): boolean {
    return patterns.some((p) => text.includes(p));
  }

  onProductSelected(data: Record<string, unknown>): void {
    this.stream.submit({ resume: data });
  }

  onFacetSelected(data: Record<string, unknown>): void {
    this.stream.submit({ resume: data });
  }

  onCartAction(data: Record<string, unknown>): void {
    this.stream.submit({ resume: data });
  }

  onOpenSearch(): void {
    this.stream.submit({ resume: { action: 'open_search' } });
  }

  onRefineSearch(): void {
    this.stream.submit({ resume: { action: 'refine_filters' } });
  }

  private scrollToBottom(): void {
    try {
      this.messagesArea.nativeElement.scrollTop =
        this.messagesArea.nativeElement.scrollHeight;
    } catch (e) {}
  }
}
