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
      <button (click)="send()" [disabled]="disabled || !text.trim()" class="send-btn">
        Send
      </button>
    </div>
  `,
  styles: [
    `
      .input-bar {
        display: flex;
        gap: 8px;
        padding: 16px;
        border-top: 1px solid #e2e8f0;
        background: white;
      }

      .input-field {
        flex: 1;
        padding: 12px 16px;
        border: 1px solid #cbd5e1;
        border-radius: 24px;
        font-size: 14px;
        outline: none;
        transition: border-color 0.2s;

        &:focus {
          border-color: #4f46e5;
          box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
        }

        &:disabled {
          background: #f8fafc;
          cursor: not-allowed;
        }
      }

      .send-btn {
        padding: 12px 24px;
        background: #4f46e5;
        color: white;
        border: none;
        border-radius: 24px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s;

        &:hover:not(:disabled) {
          background: #4338ca;
        }

        &:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
      }
    `,
  ],
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
