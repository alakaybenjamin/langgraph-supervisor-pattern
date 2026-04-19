import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { DataContext } from '@a2ui/web_core/v0_9';
import { A2uiRendererService, type BoundProperty } from '@a2ui/angular/v0_9';

interface ProductMetadata {
  id: string;
  product_type?: string;
  domain?: string;
  sensitivity?: string;
}

interface Product {
  content?: string;
  metadata?: ProductMetadata;
  score?: number;
}

/**
 * Angular implementation of the ``ProductPicker`` component declared in
 * ``backend/app/a2ui/catalogs/datagov-v1.json``. Renders a stack of
 * product cards (id, type pill, content snippet, domain · sensitivity)
 * plus three action buttons that mirror the legacy product_selection UX:
 *
 * - **Refine Filters** → ``onRefine`` action (``product.refine``)
 * - **Open Search Panel** → ``onOpenSearch`` action (``product.open_search``)
 * - **Add N to Request** → ``onConfirm`` action (``product.confirm``),
 *   primary; emits with ``context.products`` = the selected list.
 *
 * Selection state is owned by this component (a local signal). We do
 * NOT round-trip per click through ``updateDataModel`` because:
 * (a) the legacy UX never round-tripped either, and (b) doing so on
 * every checkbox tap would feel laggy under SSE latency.
 *
 * All resume payload translation lives in ``ChatService.handleA2uiAction``.
 */
@Component({
  selector: 'a2ui-datagov-product-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="product-cards">
      @for (p of products(); track productId(p)) {
        <button
          class="product-card"
          type="button"
          [class.product-card--selected]="isSelected(productId(p))"
          (click)="toggle(p)"
        >
          <div class="product-checkbox">
            @if (isSelected(productId(p))) {
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path
                  d="M2 7l4 4 6-6"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            }
          </div>
          <div class="product-body">
            <div class="product-id">
              {{ p.metadata?.id }}
              @if (p.metadata?.product_type) {
                <span class="product-type">{{ p.metadata?.product_type }}</span>
              }
            </div>
            @if (p.content) {
              <div class="product-desc">{{ truncate(p.content, 100) }}</div>
            }
            <div class="product-meta">
              {{ p.metadata?.domain }} &middot; {{ p.metadata?.sensitivity }}
            </div>
          </div>
        </button>
      }

      <div class="selection-actions">
        @if (hasRefine()) {
          <button class="action-btn secondary" type="button" (click)="refine()">
            Refine Filters
          </button>
        }
        @if (hasOpenSearch()) {
          <button class="action-btn secondary" type="button" (click)="openSearch()">
            Open Search Panel
          </button>
        }
        @if (products().length > 0) {
          <button
            class="action-btn primary"
            type="button"
            [disabled]="selectedCount() === 0"
            (click)="confirm()"
          >
            {{ confirmLabel() }}
          </button>
        }
      </div>
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
      }

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
      }

      .product-card:hover {
        border-color: #4f46e5;
        box-shadow: 0 0 0 2px rgba(79, 70, 229, 0.15);
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

      .selection-actions {
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
      }

      .action-btn.primary {
        background: #4f46e5;
        color: white;
        border-color: #4f46e5;
      }

      .action-btn.primary:hover:not(:disabled) {
        background: #4338ca;
      }

      .action-btn.primary:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }

      .action-btn.secondary {
        background: #f8fafc;
        color: #475569;
      }

      .action-btn.secondary:hover {
        background: #e2e8f0;
      }
    `,
  ],
})
export class ProductPickerComponent {
  readonly props = input<Record<string, BoundProperty<unknown>>>({});
  readonly surfaceId = input.required<string>();
  readonly componentId = input.required<string>();
  readonly dataContextPath = input<string>('/');

  private readonly rendererService = inject(A2uiRendererService);

  // Local selection state — keyed by product id so we tolerate the
  // ``products`` data-model array being replaced (e.g. after a search
  // refine round-trip) without losing selections that still match.
  private readonly selectedIds = signal<ReadonlySet<string>>(new Set());

  readonly products = computed<Product[]>(() => {
    const raw = this.props()['products']?.value();
    if (!Array.isArray(raw)) return [];
    return raw.filter(
      (v): v is Product =>
        !!v && typeof v === 'object' && 'metadata' in v,
    );
  });

  readonly selectedCount = computed<number>(() => this.selectedIds().size);

  readonly confirmLabel = computed<string>(() => {
    const tpl = this.props()['confirmLabelTemplate']?.value();
    const template =
      typeof tpl === 'string' && tpl ? tpl : 'Add {count} to Request';
    const count = this.selectedCount();
    return template.replace('{count}', count > 0 ? String(count) : '');
  });

  readonly hasRefine = computed<boolean>(
    () => this.props()['onRefine']?.value() != null,
  );
  readonly hasOpenSearch = computed<boolean>(
    () => this.props()['onOpenSearch']?.value() != null,
  );

  productId(p: Product): string {
    return p.metadata?.id ?? '';
  }

  isSelected(id: string): boolean {
    return id !== '' && this.selectedIds().has(id);
  }

  toggle(p: Product): void {
    const id = this.productId(p);
    if (!id) return;
    const next = new Set(this.selectedIds());
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    this.selectedIds.set(next);

    // Optional informational notification — most hosts ignore this and
    // wait for ``onConfirm`` instead. We still fire it for parity with
    // the catalog schema and so future hosts (e.g. analytics agents)
    // can subscribe.
    this.dispatchAction('onToggle', { value: id });
  }

  confirm(): void {
    if (this.selectedCount() === 0) return;
    const ids = this.selectedIds();
    const selected = this.products().filter((p) => ids.has(this.productId(p)));
    this.dispatchAction('onConfirm', { products: selected });
  }

  openSearch(): void {
    this.dispatchAction('onOpenSearch', {});
  }

  refine(): void {
    this.dispatchAction('onRefine', {});
  }

  truncate(text: string | undefined, maxLen: number): string {
    if (!text) return '';
    return text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
  }

  /**
   * Resolve the named action against the current data context, merge
   * the supplied context overrides, and dispatch through the surface.
   * The resolution step expands any ``{path: ...}`` bindings that the
   * backend put inside the action context.
   */
  private dispatchAction(
    propName: 'onToggle' | 'onConfirm' | 'onOpenSearch' | 'onRefine',
    contextOverrides: Record<string, unknown>,
  ): void {
    const action = this.props()[propName]?.value();
    if (!action) return;

    const surface = this.rendererService.surfaceGroup?.getSurface(
      this.surfaceId(),
    );
    if (!surface) return;

    const dataContext = new DataContext(surface, this.dataContextPath());
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const resolved = dataContext.resolveAction(action as any);
    const merged = mergeContext(resolved, contextOverrides);
    void surface.dispatchAction(merged, this.componentId());
  }
}

function mergeContext(
  action: unknown,
  overrides: Record<string, unknown>,
): unknown {
  if (!action || typeof action !== 'object') return action;
  const a = action as { event?: { context?: Record<string, unknown> } };
  if (!a.event) return action;
  return {
    ...a,
    event: {
      ...a.event,
      context: { ...(a.event.context ?? {}), ...overrides },
    },
  };
}
