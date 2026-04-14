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
        @if (chatService.loading()) {
          <div class="typing-indicator">
            @if (chatService.currentStep()) {
              <span class="step-label">{{ stepLabel(chatService.currentStep()!) }}</span>
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
        align-items: center;
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

      .step-label {
        font-size: 12px;
        color: #6366f1;
        font-weight: 500;
        margin-right: 4px;
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
  chatService = inject(ChatService);

  @ViewChild('messagesArea') private messagesArea!: ElementRef;

  ngAfterViewChecked(): void {
    this.scrollToBottom();
  }

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
        this.addUserMessageAndResume(message, { action: 'user_message', text: message });
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

      if (interruptType === 'product_selection') {
        if (searchIntent) {
          this.addUserMessageAndResume(message, { action: 'open_search' });
          return;
        }
        if (refineIntent || addMoreIntent) {
          this.addUserMessageAndResume(message, { action: 'refine_filters' });
          return;
        }
      }

      if (interruptType === 'facet_selection' && refineIntent) {
        this.addUserMessageAndResume(message, { value: 'all' });
        return;
      }
    }
    this.chatService.sendMessage(message);
  }

  private addUserMessageAndResume(
    text: string,
    data: Record<string, unknown>
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
    this.chatService.resumeWithData({ confirmed: yes, action: yes ? 'confirm' : 'edit' });
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
