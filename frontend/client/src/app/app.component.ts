import { Component } from '@angular/core';
import { ChatComponent } from './features/chat/chat.component';
import { McpPanelComponent } from './features/mcp-panel/mcp-panel.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [ChatComponent, McpPanelComponent],
  template: `
    <div class="app-layout">
      <app-chat class="chat-area" />
      <app-mcp-panel />
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
        height: 100vh;
      }

      .app-layout {
        display: flex;
        height: 100%;
      }

      .chat-area {
        flex: 1;
        min-width: 0;
      }
    `,
  ],
})
export class AppComponent {}
