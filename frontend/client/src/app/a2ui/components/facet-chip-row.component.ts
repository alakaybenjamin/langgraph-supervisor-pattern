import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
} from '@angular/core';
import { DataContext } from '@a2ui/web_core/v0_9';
import { A2uiRendererService, type BoundProperty } from '@a2ui/angular/v0_9';

interface FacetOption {
  id: string;
  label: string;
}

/**
 * Angular implementation of the ``FacetChipRow`` component declared in
 * ``backend/app/a2ui/catalogs/datagov-v1.json``. Renders a row of
 * selectable chips; clicking a chip dispatches the ``onSelect`` action
 * configured by the backend builder, with the clicked option's id
 * merged into ``event.context.value``.
 *
 * The prompt above the chips is intentionally rendered by the host
 * chat bubble (``MessageComponent`` reads it from the interrupt's
 * top-level ``message`` field), not by this component. The catalog
 * schema keeps ``prompt`` optional so a future non-chat host can
 * still bind it if needed.
 *
 * All action routing — including translating the fired event back to
 * the legacy ``{facet, value}`` resume payload — happens in the
 * ``actionHandler`` registered in ``app.config.ts``. This component
 * stays purely presentational.
 */
@Component({
  selector: 'a2ui-datagov-facet-chip-row',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="facet-options">
      @for (opt of options(); track opt.id) {
        <button
          class="facet-chip"
          type="button"
          (click)="onChipClick(opt.id)"
        >
          {{ opt.label }}
        </button>
      }
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
      }

      .facet-options {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
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
      }

      .facet-chip:hover {
        border-color: #4f46e5;
        background: #eef2ff;
        color: #4f46e5;
      }
    `,
  ],
})
export class FacetChipRowComponent {
  readonly props = input<Record<string, BoundProperty<any>>>({});
  readonly surfaceId = input.required<string>();
  readonly componentId = input.required<string>();
  readonly dataContextPath = input<string>('/');

  private readonly rendererService = inject(A2uiRendererService);

  readonly options = computed<FacetOption[]>(() => {
    const value = this.props()['options']?.value();
    if (!Array.isArray(value)) return [];
    return value
      .filter(
        (v): v is FacetOption =>
          !!v &&
          typeof v === 'object' &&
          typeof (v as { id?: unknown }).id === 'string' &&
          typeof (v as { label?: unknown }).label === 'string',
      )
      .map((opt) => ({ id: opt.id, label: opt.label }));
  });

  /**
   * Fire the configured ``onSelect`` action, merging the clicked chip id
   * into the action's event context as ``value``. The backend builder
   * already put ``facet`` / ``step`` / ``prompt_id`` into the context,
   * so downstream handlers receive a full routing envelope.
   */
  onChipClick(optionId: string): void {
    const action = this.props()['onSelect']?.value();
    if (!action) return;

    const surface = this.rendererService.surfaceGroup?.getSurface(
      this.surfaceId(),
    );
    if (!surface) return;

    const dataContext = new DataContext(surface, this.dataContextPath());
    const resolved = dataContext.resolveAction(action);
    const withValue = mergeSelectedValue(resolved, optionId);
    surface.dispatchAction(withValue, this.componentId());
  }
}

/**
 * Clone the action and merge ``{value: optionId}`` into its event context.
 * Kept as a pure function so the component is trivially testable.
 */
function mergeSelectedValue(
  action: unknown,
  optionId: string,
): unknown {
  if (!action || typeof action !== 'object') return action;
  const a = action as { event?: { context?: Record<string, unknown> } };
  if (!a.event) return action;
  return {
    ...a,
    event: {
      ...a.event,
      context: { ...(a.event.context ?? {}), value: optionId },
    },
  };
}
