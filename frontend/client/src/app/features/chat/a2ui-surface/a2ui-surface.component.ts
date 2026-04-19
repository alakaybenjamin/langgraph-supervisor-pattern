import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
} from '@angular/core';
import type { A2uiMessage } from '@a2ui/web_core/v0_9';
import { A2uiRendererService, SurfaceComponent } from '@a2ui/angular/v0_9';

import type { A2uiInterrupt } from '../../../core/models/chat.model';

/**
 * Thin wrapper that hands an A2UI interrupt payload to the renderer
 * service and then mounts the v0.9 ``<a2ui-v09-surface>`` by id.
 *
 * The actual action routing (facet/product/cart events → resume_data)
 * happens in the global ``actionHandler`` wired into
 * ``A2UI_RENDERER_CONFIG``; this component stays presentational.
 */
@Component({
  selector: 'app-a2ui-surface',
  standalone: true,
  imports: [SurfaceComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a2ui-v09-surface
      [surfaceId]="surfaceId()"
    />
  `,
  styles: [
    `
      :host {
        display: block;
        margin-top: 12px;
      }
    `,
  ],
})
export class A2uiSurfaceComponent {
  readonly interrupt = input.required<A2uiInterrupt>();

  private readonly rendererService = inject(A2uiRendererService);

  readonly surfaceId = computed(() => this.interrupt().surface_id);

  constructor() {
    // Re-process messages whenever the bound interrupt changes. The
    // MessageProcessor is idempotent for ``createSurface`` with the same
    // id, so re-mounting the same surface (e.g. on Angular input churn)
    // does not duplicate state.
    effect(() => {
      const payload = this.interrupt();
      const messages = payload.a2ui_messages ?? [];
      if (!messages.length) return;
      this.rendererService.processMessages(messages as A2uiMessage[]);
    });
  }
}
