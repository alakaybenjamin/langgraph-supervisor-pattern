import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  ActionButton,
  ChatMessage,
  FacetOption,
  InterruptOf,
  InterruptType,
  Product,
  asInterrupt,
  hasInterruptType,
} from '../../../core/models/chat.model';

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
        @if (isStaleInteractive()) {
          <!-- The interrupt this bubble carried was superseded before
               the user acted on it. Per UX: drop the original prompt
               text + the rich widget entirely and replace them with a
               single "User Skipped X" notice in the badge styling. The
               bubble shape itself is preserved so the transcript still
               reads naturally. -->
          <div class="skipped-notice">
            User Skipped {{ skippedActionLabel() }}
          </div>
        } @else {
          <div class="content" [innerHTML]="formatContent(msg.content)"></div>
        }

        <!-- Facet selection: domain / type chips -->
        @if (facetOptions().length > 0 && isActionable()) {
          <div class="facet-options">
            @for (opt of facetOptions(); track opt.id) {
              <button class="facet-chip" (click)="selectFacet(opt.id)">
                {{ opt.label }}
              </button>
            }
          </div>
        }

        <!-- Product selection (multi-select) -->
        @if (isProductSelection() && isActionable()) {
          <div class="product-cards">
            @for (p of products(); track $index) {
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
        @if (cartActions().length > 0 && isActionable()) {
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
        @if (isConfirmation() && isActionable()) {
          @if (confirmProductsSummary()) {
            <div
              class="confirm-summary"
              [innerHTML]="formatContent(confirmProductsSummary())"
            ></div>
          }
          @if (confirmFormDataEntries().length > 0) {
            <div class="confirm-form">
              <div class="confirm-form-title">Your answers</div>
              @for (entry of confirmFormDataEntries(); track entry.key) {
                <div class="confirm-form-row">
                  <span class="confirm-form-key">{{ entry.key }}:</span>
                  <span class="confirm-form-value">{{ entry.value }}</span>
                </div>
              }
            </div>
          }
          <div class="confirm-actions">
            @if (confirmActions().length > 0) {
              @for (action of confirmActions(); track action.id) {
                <button
                  class="confirm-btn"
                  [class.yes]="isPrimaryConfirmAction(action.id)"
                  [class.no]="!isPrimaryConfirmAction(action.id)"
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

      /* Confirmation review */
      .confirm-summary {
        margin-top: 12px;
        padding: 10px 12px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        font-size: 13px;
        color: #334155;
        line-height: 1.6;
      }

      .confirm-form {
        margin-top: 8px;
        padding: 10px 12px;
        background: #fefce8;
        border: 1px solid #fde68a;
        border-radius: 8px;
        font-size: 13px;
        color: #78350f;
      }

      .confirm-form-title {
        font-weight: 600;
        margin-bottom: 6px;
      }

      .confirm-form-row {
        display: flex;
        gap: 6px;
        margin-bottom: 2px;
      }

      .confirm-form-key {
        font-weight: 500;
        color: #92400e;
      }

      .confirm-form-value {
        color: #78350f;
        word-break: break-word;
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

      /* Replaces the original prompt text + rich widget on a bubble
         whose interrupt was superseded before the user acted on it.
         Same visual language as the previous "Superseded" badge so the
         transcript reads as a clear, low-key skip notice. */
      .skipped-notice {
        display: inline-block;
        font-size: 11px;
        color: #64748b;
        background: #f1f5f9;
        border: 1px dashed #cbd5e1;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 500;
      }
    `,
  ],
})
export class MessageComponent {
  @Input({ required: true }) msg!: ChatMessage;
  /**
   * The ``prompt_id`` of the interrupt currently awaiting user input,
   * propagated down from ``ChatService.currentInterrupt``. When this
   * does NOT match the message's own ``prompt_id`` the conversation has
   * moved on (the user typed a FAQ question, navigated, the agent
   * committed, etc.) and this message's chips/buttons MUST stop being
   * actionable to prevent stale clicks. ``null`` means there is no
   * active interrupt at all (e.g. mid-FAQ answer streaming) so every
   * past interactive bubble is stale.
   */
  @Input() activePromptId: string | null = null;
  @Output() productSelected = new EventEmitter<Record<string, unknown>>();
  @Output() facetSelected = new EventEmitter<Record<string, unknown>>();
  @Output() cartAction = new EventEmitter<Record<string, unknown>>();
  @Output() openSearchPanel = new EventEmitter<void>();
  @Output() refineSearch = new EventEmitter<void>();

  /** Local flag — flips ``true`` when the user clicks a button on this
   * message. Distinct from staleness: a clicked message is "Completed",
   * a stale-but-unclicked one is "Superseded".
   */
  resolved = false;
  selectedProducts: Product[] = [];

  /** This message's own prompt id, if it carries an interrupt. */
  private myPromptId(): string | null {
    const v = this.msg.interrupt?.interrupt_value as
      | { prompt_id?: string }
      | undefined;
    return v?.prompt_id ?? null;
  }

  /**
   * True when this message rendered an interrupt that has since been
   * superseded by a newer one (or by the workflow moving on without a
   * new interrupt at all). Drives both the "Superseded" badge and the
   * dimmed bubble.
   */
  isStale(): boolean {
    if (!this.msg.interrupt) return false;
    const my = this.myPromptId();
    if (!my) return false; // can't tell — leave it alone
    return this.activePromptId !== my;
  }

  /** "Show the interactive UI here?" — only when not clicked AND not
   * stale. Single source of truth used by every ``@if`` guard above.
   */
  isActionable(): boolean {
    return !this.resolved && !this.isStale();
  }

  /** True when the bubble originally rendered an actionable widget
   * (chips, product picker, cart, confirmation, MCP App) AND that
   * interrupt has since been superseded. ``narrow_message`` bubbles are
   * plain text and never get the skipped-notice treatment — there's
   * nothing to skip past, the text alone is the message.
   */
  isStaleInteractive(): boolean {
    if (!this.isStale()) return false;
    const t = (this.msg.interrupt?.interrupt_value as { type?: string })?.type;
    return t !== undefined && t !== 'narrow_message';
  }

  /** Human-readable label for the skipped widget, dropped into
   * "User Skipped {label}". Kept in sync with the interrupt union in
   * ``chat.model.ts``. */
  skippedActionLabel(): string {
    const t = (this.msg.interrupt?.interrupt_value as { type?: string })?.type;
    switch (t) {
      case 'product_selection':
        return 'Data Product Selection';
      case 'facet_selection':
        return 'Filter Selection';
      case 'cart_review':
        return 'Cart Review';
      case 'confirmation':
        return 'Confirmation';
      case 'mcp_app':
        return 'App Action';
      default:
        return 'Action';
    }
  }

  /**
   * Single typed narrowing helper — the frontend equivalent of the
   * LangChain-docs `extractStructuredOutput<T>()` pattern. Callers get
   * back a fully typed interrupt of the requested variant, or `null` if
   * the message has a different interrupt type / is missing required
   * fields.
   */
  private interrupt<T extends InterruptType>(type: T): InterruptOf<T> | null {
    return asInterrupt(this.msg.interrupt?.interrupt_value, type);
  }

  facetOptions(): FacetOption[] {
    return this.interrupt('facet_selection')?.options ?? [];
  }

  isProductSelection(): boolean {
    return hasInterruptType(this.msg.interrupt?.interrupt_value, 'product_selection');
  }

  products(): Product[] {
    return this.interrupt('product_selection')?.products ?? [];
  }

  cartActions(): ActionButton[] {
    return this.interrupt('cart_review')?.actions ?? [];
  }

  confirmActions(): ActionButton[] {
    return this.interrupt('confirmation')?.actions ?? [];
  }

  isConfirmation(): boolean {
    return hasInterruptType(this.msg.interrupt?.interrupt_value, 'confirmation');
  }

  confirmProductsSummary(): string {
    return this.interrupt('confirmation')?.products_summary ?? '';
  }

  confirmFormDataEntries(): { key: string; value: string }[] {
    const data = this.interrupt('confirmation')?.form_data;
    if (!data || typeof data !== 'object') return [];
    return Object.entries(data).map(([key, value]) => ({
      key,
      value:
        typeof value === 'string'
          ? value
          : value === null || value === undefined
            ? ''
            : JSON.stringify(value),
    }));
  }

  isPrimaryConfirmAction(id: string): boolean {
    return id === 'submit' || id === 'confirm';
  }

  selectFacet(value: string): void {
    this.resolved = true;
    const facet = this.interrupt('facet_selection')?.facet ?? '';
    this.facetSelected.emit({ value, facet });
  }

  isProductSelected(product: Product): boolean {
    return this.selectedProducts.some(
      (p) => p.metadata?.id === product.metadata?.id,
    );
  }

  toggleProduct(product: Product): void {
    const idx = this.selectedProducts.findIndex(
      (p) => p.metadata?.id === product.metadata?.id,
    );
    if (idx >= 0) {
      this.selectedProducts = this.selectedProducts.filter((_, i) => i !== idx);
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
    if (action === 'add_more') {
      this.cartAction.emit({ action: 'add_more' });
      return;
    }
    this.productSelected.emit({ action });
  }

  confirm(yes: boolean): void {
    this.resolved = true;
    this.productSelected.emit({ action: yes ? 'submit' : 'edit' });
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
