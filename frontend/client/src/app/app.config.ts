import { ApplicationConfig, inject, provideZoneChangeDetection } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { A2UI_RENDERER_CONFIG, A2uiRendererService } from '@a2ui/angular/v0_9';
import type { A2uiClientAction } from '@a2ui/web_core/v0_9';

import { routes } from './app.routes';
import { DatagovCatalog } from './a2ui/datagov-catalog';
import { ChatService } from './core/services/chat.service';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes),
    provideHttpClient(),

    // A2UI v0.9 renderer configuration. ``actionHandler`` is invoked
    // whenever a component in any surface dispatches an action; we route
    // those into ``ChatService.handleA2uiAction`` which translates to
    // the legacy ``resume_data`` shape so the LangGraph subgraph's
    // ``_apply_structured_answer`` sees identical inputs whether the
    // interrupt took the legacy path or the A2UI path.
    {
      provide: A2UI_RENDERER_CONFIG,
      useFactory: () => {
        const chat = inject(ChatService);
        return {
          catalogs: [new DatagovCatalog()],
          actionHandler: (action: A2uiClientAction) =>
            chat.handleA2uiAction(action),
        };
      },
    },
    A2uiRendererService,
  ],
};
