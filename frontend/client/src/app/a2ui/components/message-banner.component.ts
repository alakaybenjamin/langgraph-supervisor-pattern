import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
} from '@angular/core';
import type { BoundProperty } from '@a2ui/angular/v0_9';

type BannerVariant = 'info' | 'warning' | 'success';

/**
 * Angular implementation of the ``MessageBanner`` component. Presentational
 * only — no actions. Used as a helper companion to interactive components
 * when we need to show a one-line status above an input.
 */
@Component({
  selector: 'a2ui-datagov-message-banner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<div class="banner" [class]="'banner--' + variant()">{{ text() }}</div>`,
  styles: [
    `
      .banner {
        padding: 8px 12px;
        border-radius: 8px;
        font-size: 13px;
        line-height: 1.5;
      }
      .banner--info {
        background: #eff6ff;
        color: #1e40af;
        border: 1px solid #bfdbfe;
      }
      .banner--warning {
        background: #fffbeb;
        color: #92400e;
        border: 1px solid #fde68a;
      }
      .banner--success {
        background: #ecfdf5;
        color: #065f46;
        border: 1px solid #a7f3d0;
      }
    `,
  ],
})
export class MessageBannerComponent {
  readonly props = input<Record<string, BoundProperty<any>>>({});
  readonly surfaceId = input.required<string>();
  readonly componentId = input.required<string>();
  readonly dataContextPath = input<string>('/');

  readonly text = computed<string>(() => {
    const value = this.props()['text']?.value();
    return typeof value === 'string' ? value : '';
  });

  readonly variant = computed<BannerVariant>(() => {
    const raw = this.props()['variant']?.value();
    return raw === 'warning' || raw === 'success' ? raw : 'info';
  });
}
