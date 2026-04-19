import { z } from 'zod';
import { AngularCatalog, type AngularComponentImplementation } from '@a2ui/angular/v0_9';

import { FacetChipRowComponent } from './components/facet-chip-row.component';
import { MessageBannerComponent } from './components/message-banner.component';
import { ProductPickerComponent } from './components/product-picker.component';

/**
 * Catalog id for our custom "datagov.local:v1" catalog. Must match the
 * ``catalogId`` declared in ``backend/app/a2ui/catalogs/datagov-v1.json``
 * and the ``A2UI_CATALOG_ID`` constant in ``backend/app/a2ui/builders.py``.
 */
export const DATAGOV_CATALOG_ID = 'datagov.local:v1';

// Schemas are permissive because runtime validation happens on the
// backend via the JSON catalog file; here we just need the binder to
// know which property names to expose. The ``as any`` cast bridges the
// zod-v4-at-root / zod-v3-inside-@a2ui gap: structurally they match but
// TS sees them as different classes.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const anySchema = (shape: Record<string, unknown>) =>
  z.object(shape as Record<string, z.ZodTypeAny>).passthrough() as unknown as any;

const DATAGOV_COMPONENTS: AngularComponentImplementation[] = [
  {
    name: 'FacetChipRow',
    schema: anySchema({
      prompt: z.any().optional(),
      facet: z.any(),
      options: z.any(),
      onSelect: z.any(),
    }),
    component: FacetChipRowComponent,
  },
  {
    name: 'ProductPicker',
    schema: anySchema({
      products: z.any(),
      confirmLabelTemplate: z.any().optional(),
      onToggle: z.any().optional(),
      onConfirm: z.any(),
      onOpenSearch: z.any().optional(),
      onRefine: z.any().optional(),
    }),
    component: ProductPickerComponent,
  },
  {
    name: 'MessageBanner',
    schema: anySchema({
      text: z.any(),
      variant: z.string().optional(),
    }),
    component: MessageBannerComponent,
  },
];

/**
 * Angular catalog that backs the ``datagov.local:v1`` A2UI catalog.
 * Registered via ``A2UI_RENDERER_CONFIG`` in ``app.config.ts``.
 */
export class DatagovCatalog extends AngularCatalog {
  constructor() {
    super(DATAGOV_CATALOG_ID, DATAGOV_COMPONENTS);
  }
}
