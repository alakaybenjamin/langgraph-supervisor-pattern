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

        <!-- Facet selection: domain / type chips -->
        @if (facetOptions().length > 0 && !resolved) {
          <div class="facet-options">
            @for (opt of facetOptions(); track opt.id) {
              <button class="facet-chip" (click)="selectFacet(opt.id)">
                {{ opt.label }}
              </button>
            }
          </div>
        }

        <!-- Product selection (multi-select) -->
        @if (isProductSelection() && !resolved) {
          <div class="product-cards">
            @for (p of products(); track p.metadata?.id) {
              <button
                class="product-card"
                [class.product-card--selected]="isProductSelected(p)"
                (click)="toggleProduct(p)"
              >
                <div class="product-checkbox">
                  @if (isProductSelected(p)) {
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <path d="M2 7l4 4 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                  }
                </div>
                <div class="product-body">
                  <div class="product-id">{{ p.metadata?.id }}
                    <span class="product-type">{{ p.metadata?.product_type }}</span>
                  </div>
                  <div class="product-desc">{{ truncate(p.content, 100) }}</div>
                  <div class="product-meta">
                    {{ p.metadata?.domain }} &middot; {{ p.metadata?.sensitivity }}
                  </div>
                </div>
              </button>
            }
            <div class="selection-actions">
              <button class="action-btn secondary" (click)="refineFilters()">
                Refine Filters
              </button>
              <button class="action-btn secondary" (click)="openSearch()">
                Open Search Panel
              </button>
              @if (products().length > 0) {
                <button
                  class="action-btn primary"
                  [disabled]="selectedProducts.length === 0"
                  (click)="confirmProductSelection()"
                >
                  Add {{ selectedProducts.length || '' }} to Request
                </button>
              }
            </div>
          </div>
        }

        <!-- Cart review -->
        @if (cartActions().length > 0 && !resolved) {
          <div class="cart-actions">
            @for (action of cartActions(); track action.id) {
              <button
                class="action-btn"
                [class.primary]="action.id === 'fill_forms'"
                [class.secondary]="action.id !== 'fill_forms'"
                (click)="selectCartAction(action.id)"
              >
                {{ action.label }}
              </button>
            }
          </div>
        }

        <!-- Confirmation -->
        @if (isConfirmation() && !resolved) {
          <div class="confirm-actions">
            @if (confirmActions().length > 0) {
              @for (action of confirmActions(); track action.id) {
                <button
                  class="confirm-btn"
                  [class.yes]="action.id === 'confirm'"
                  [class.no]="action.id !== 'confirm'"
                  (click)="confirmAction(action.id)"
                >
                  {{ action.label }}
                </button>
              }
            } @else {
              <button class="confirm-btn yes" (click)="confirm(true)">Yes, submit</button>
              <button class="confirm-btn no" (click)="confirm(false)">Go back and edit</button>
            }
          </div>
        }

        @if (resolved) {
          <div class="resolved-badge">Completed</div>
        }

        <div class="time">{{ msg.timestamp | date : 'HH:mm' }}</div>
      </div>
    </div>
  `,
  styles: [
    `
      .message {
        display: flex;
        gap: 12px;
        margin-bottom: 16px;
        max-width: 85%;

        &.user {
          margin-left: auto;
          flex-direction: row-reverse;
        }

        &.system {
          max-width: 100%;
          justify-content: center;

          .bubble {
            background: #fff3cd;
            color: #856404;
            border-radius: 8px;
          }

          .avatar {
            display: none;
          }
        }
      }

      .avatar {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 600;
        font-size: 14px;
        flex-shrink: 0;
      }

      .user .avatar {
        background: #4f46e5;
        color: white;
      }

      .assistant .avatar {
        background: #059669;
        color: white;
      }

      .bubble {
        padding: 12px 16px;
        border-radius: 16px;
        line-height: 1.5;
        word-break: break-word;
      }

      .user .bubble {
        background: #4f46e5;
        color: white;
        border-bottom-right-radius: 4px;
      }

      .assistant .bubble {
        background: #f1f5f9;
        color: #1e293b;
        border-bottom-left-radius: 4px;
      }

      .time {
        font-size: 11px;
        opacity: 0.6;
        margin-top: 4px;
      }

      /* Facet chips */
      .facet-options {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 12px;
      }

      .facet-chip {
        padding: 8px 16px;
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 20px;
        cursor: pointer;
        font-size: 13px;
        font-weight: 500;
        color: #334155;
        transition: all 0.15s;

        &:hover {
          border-color: #4f46e5;
          background: #eef2ff;
          color: #4f46e5;
        }
      }

      /* Product cards */
      .product-cards {
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin-top: 12px;
      }

      .product-card {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        width: 100%;
        text-align: left;
        padding: 12px 14px;
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        cursor: pointer;
        transition: all 0.15s;

        &:hover {
          border-color: #4f46e5;
          box-shadow: 0 0 0 2px rgba(79, 70, 229, 0.15);
        }
      }

      .product-card--selected {
        border-color: #4f46e5;
        background: #eef2ff;
      }

      .product-checkbox {
        width: 20px;
        height: 20px;
        min-width: 20px;
        border: 2px solid #d1d5db;
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-top: 2px;
        transition: all 0.15s;
        color: transparent;
      }

      .product-card--selected .product-checkbox {
        background: #4f46e5;
        border-color: #4f46e5;
        color: white;
      }

      .product-body {
        flex: 1;
        min-width: 0;
      }

      .product-id {
        font-weight: 600;
        font-size: 13px;
        color: #1e293b;
        margin-bottom: 4px;
      }

      .product-type {
        display: inline-block;
        background: #ede9fe;
        color: #6d28d9;
        font-size: 11px;
        font-weight: 500;
        padding: 2px 6px;
        border-radius: 4px;
        margin-left: 6px;
        text-transform: uppercase;
      }

      .product-desc {
        font-size: 13px;
        color: #334155;
        margin-bottom: 4px;
      }

      .product-meta {
        font-size: 11px;
        color: #94a3b8;
      }

      /* Selection & Cart & Confirmation actions */
      .selection-actions,
      .cart-actions {
        display: flex;
        gap: 8px;
        margin-top: 12px;
        flex-wrap: wrap;
      }

      .action-btn {
        padding: 10px 20px;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        font-weight: 600;
        font-size: 13px;
        cursor: pointer;
        transition: all 0.15s;

        &.primary {
          background: #4f46e5;
          color: white;
          border-color: #4f46e5;

          &:hover:not(:disabled) {
            background: #4338ca;
          }

          &:disabled {
            opacity: 0.5;
            cursor: not-allowed;
          }
        }

        &.secondary {
          background: #f8fafc;
          color: #475569;

          &:hover {
            background: #e2e8f0;
          }
        }
      }

      .confirm-actions {
        display: flex;
        gap: 8px;
        margin-top: 12px;
        flex-wrap: wrap;
      }

      .confirm-btn {
        padding: 10px 20px;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        font-size: 13px;
        cursor: pointer;
        transition: all 0.15s;

        &.yes {
          background: #059669;
          color: white;

          &:hover {
            background: #047857;
          }
        }

        &.no {
          background: #f1f5f9;
          color: #475569;
          border: 1px solid #e2e8f0;

          &:hover {
            background: #e2e8f0;
          }
        }
      }

      .resolved-badge {
        display: inline-block;
        margin-top: 8px;
        font-size: 11px;
        color: #059669;
        background: #ecfdf5;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 500;
      }
    `,
  ],
})
export class MessageComponent {
  @Input({ required: true }) msg!: ChatMessage;
  @Output() productSelected = new EventEmitter<Record<string, unknown>>();
  @Output() confirmed = new EventEmitter<boolean>();
  @Output() facetSelected = new EventEmitter<Record<string, unknown>>();
  @Output() cartAction = new EventEmitter<Record<string, unknown>>();
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

  confirmActions(): { id: string; label: string }[] {
    const val = this.msg.interrupt?.interrupt_value;
    if (val?.['type'] === 'confirmation' && val?.['actions']) {
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

  isProductSelected(product: any): boolean {
    return this.selectedProducts.some(
      (p: any) => p.metadata?.id === product.metadata?.id
    );
  }

  toggleProduct(product: any): void {
    const idx = this.selectedProducts.findIndex(
      (p: any) => p.metadata?.id === product.metadata?.id
    );
    if (idx >= 0) {
      this.selectedProducts = this.selectedProducts.filter(
        (_, i) => i !== idx
      );
    } else {
      this.selectedProducts = [...this.selectedProducts, product];
    }
  }

  confirmProductSelection(): void {
    this.resolved = true;
    this.productSelected.emit({
      action: 'select',
      products: this.selectedProducts,
    });
  }

  openSearch(): void {
    this.resolved = true;
    this.openSearchPanel.emit();
  }

  refineFilters(): void {
    this.resolved = true;
    this.refineSearch.emit();
  }

  selectCartAction(action: string): void {
    this.resolved = true;
    this.cartAction.emit({ action });
  }

  confirmAction(action: string): void {
    this.resolved = true;
    if (action === 'confirm') {
      this.confirmed.emit(true);
    } else if (action === 'edit') {
      this.confirmed.emit(false);
    } else if (action === 'add_more') {
      this.cartAction.emit({ action: 'add_more' });
    }
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
