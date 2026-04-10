import {
  Component,
  inject,
  OnDestroy,
  signal,
  effect,
  ElementRef,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ChatService } from '../../core/services/chat.service';
import { McpService } from '../../core/services/mcp.service';

@Component({
  selector: 'app-mcp-panel',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="panel" [class.open]="isOpen()">
      <div class="panel-header">
        <h3>{{ panelTitle() }}</h3>
        <div class="panel-header__actions">
          @if (showAddMore()) {
            <button class="add-more-btn" (click)="addMoreProducts()">+ Add More Products</button>
          }
          <button class="close-btn" (click)="close()">&#10005;</button>
        </div>
      </div>
      <div class="panel-body">
        @if (mcpService.loading()) {
          <div class="loading">Loading...</div>
        } @else if (iframeHtml()) {
          <iframe
            #mcpFrame
            class="mcp-iframe"
            sandbox="allow-scripts allow-same-origin"
            [srcdoc]="iframeHtml()"
          ></iframe>
        }
      </div>
    </div>
  `,
  styles: [
    `
      .panel {
        width: 0;
        overflow: hidden;
        transition: width 0.3s ease;
        background: white;
        border-left: 1px solid #e2e8f0;
        display: flex;
        flex-direction: column;
        height: 100%;

        &.open {
          width: 50%;
          min-width: 400px;
        }
      }

      .panel-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 20px;
        border-bottom: 1px solid #e2e8f0;

        h3 {
          margin: 0;
          font-size: 16px;
          font-weight: 600;
          color: #1e293b;
        }
      }

      .panel-header__actions {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .add-more-btn {
        padding: 6px 14px;
        background: transparent;
        color: #4f46e5;
        border: 1px solid #4f46e5;
        border-radius: 6px;
        cursor: pointer;
        font-size: 12px;
        font-weight: 600;
        transition: all 0.15s;
        white-space: nowrap;

        &:hover {
          background: #4f46e5;
          color: white;
        }
      }

      .close-btn {
        background: transparent;
        border: none;
        font-size: 18px;
        cursor: pointer;
        color: #64748b;
        padding: 4px 8px;
        border-radius: 4px;

        &:hover {
          background: #f1f5f9;
        }
      }

      .panel-body {
        flex: 1;
        overflow: hidden;
      }

      .loading {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 200px;
        color: #64748b;
      }

      .mcp-iframe {
        width: 100%;
        height: 100%;
        border: none;
      }
    `,
  ],
})
export class McpPanelComponent implements OnDestroy {
  chatService = inject(ChatService);
  mcpService = inject(McpService);
  private sanitizer = inject(DomSanitizer);

  isOpen = signal(false);
  iframeHtml = signal<SafeHtml | null>(null);
  panelTitle = signal('MCP App');
  showAddMore = signal(false);

  @ViewChild('mcpFrame') mcpFrame!: ElementRef<HTMLIFrameElement>;

  private messageHandler = this.onIframeMessage.bind(this);
  private pendingToolPayload: Record<string, unknown> | null = null;
  private appInitialized = false;
  private currentEndpoint = '/mcp/question-form';

  constructor() {
    window.addEventListener('message', this.messageHandler);

    effect(() => {
      const interrupt = this.chatService.currentInterrupt();
      if (interrupt?.interrupt) {
        const val = interrupt.interrupt.interrupt_value;
        if (val?.['type'] === 'mcp_app') {
          this.openMcpApp(val as Record<string, unknown>);
        } else {
          this.isOpen.set(false);
        }
      } else {
        this.isOpen.set(false);
        this.iframeHtml.set(null);
        this.mcpService.clear();
      }
    });
  }

  ngOnDestroy(): void {
    window.removeEventListener('message', this.messageHandler);
  }

  async openMcpApp(payload: Record<string, unknown>): Promise<void> {
    this.isOpen.set(true);
    this.appInitialized = false;
    this.pendingToolPayload = payload;

    const endpoint = (payload['mcp_endpoint'] as string) || '/mcp/question-form';
    this.currentEndpoint = endpoint;
    this.mcpService.setEndpoint(endpoint);

    if (endpoint.includes('search-app')) {
      this.panelTitle.set('Search Data Products');
      this.showAddMore.set(false);
    } else {
      this.panelTitle.set('Data Access Form');
      this.showAddMore.set(true);
    }

    const resourceUri = payload['resource_uri'] as string;
    try {
      const html = await this.mcpService.fetchAppHtml(resourceUri, endpoint);
      this.iframeHtml.set(
        this.sanitizer.bypassSecurityTrustHtml(html)
      );
    } catch (e) {
      console.error('Failed to load MCP App', e);
      this.iframeHtml.set(
        this.sanitizer.bypassSecurityTrustHtml(
          '<p style="padding:20px;color:red;">Failed to load app</p>'
        )
      );
    }
  }

  close(): void {
    this.isOpen.set(false);
    this.iframeHtml.set(null);
    this.mcpService.clear();
    this.pendingToolPayload = null;
    this.appInitialized = false;
    this.showAddMore.set(false);
  }

  addMoreProducts(): void {
    this.chatService.resumeWithData({ action: 'add_more' });
    this.close();
  }

  private onIframeMessage(event: MessageEvent): void {
    const data = event.data;
    if (!data || typeof data !== 'object' || data.jsonrpc !== '2.0') {
      return;
    }

    if (!this.isOpen()) return;

    const iframe = this.mcpFrame?.nativeElement;

    if (iframe && event.source === iframe.contentWindow) {
      if (data.method && data.id != null) {
        this.handleRequest(data, iframe);
      } else if (data.method && data.id == null) {
        this.handleNotification(data);
      }
      return;
    }

    if (!iframe && data.method) {
      this.waitForIframe().then((el) => {
        if (!el || event.source !== el.contentWindow) return;
        if (data.id != null) {
          this.handleRequest(data, el);
        } else {
          this.handleNotification(data);
        }
      });
    }
  }

  private handleRequest(
    msg: { jsonrpc: string; id: number; method: string; params?: any },
    iframe: HTMLIFrameElement
  ): void {
    const respond = (result: any) => {
      iframe.contentWindow?.postMessage(
        { jsonrpc: '2.0', id: msg.id, result },
        '*'
      );
    };

    switch (msg.method) {
      case 'ui/initialize':
        respond({
          protocolVersion: msg.params?.protocolVersion ?? '2026-01-26',
          hostInfo: { name: 'DataGovernanceChat', version: '1.0.0' },
          hostCapabilities: {
            updateModelContext: { text: {} },
            message: { text: {} },
          },
          hostContext: {
            theme: 'light',
            displayMode: 'inline',
          },
        });
        break;

      case 'ui/update-model-context':
        respond({});
        break;

      case 'ui/message':
        respond({});
        this.handleAppMessage(msg.params);
        break;

      case 'ui/open-link':
        respond({ isError: false });
        break;

      case 'ui/download-file':
        respond({ isError: true });
        break;

      case 'ui/request-display-mode':
        respond({ mode: 'inline' });
        break;

      case 'ui/resource-teardown':
        respond({});
        break;

      case 'ping':
        respond({});
        break;

      case 'tools/call':
        this.handleToolCall(msg, iframe);
        break;

      default:
        console.debug('[MCP Host] Unhandled request:', msg.method);
        respond({});
        break;
    }
  }

  private handleNotification(msg: {
    method: string;
    params?: any;
  }): void {
    switch (msg.method) {
      case 'ui/notifications/initialized':
        this.appInitialized = true;
        this.sendToolResultToApp();
        break;

      case 'ui/notifications/size-changed':
        break;

      case 'ui/notifications/request-teardown':
        this.close();
        break;

      default:
        console.debug('[MCP Host] Unhandled notification:', msg.method);
        break;
    }
  }

  private async sendToolResultToApp(): Promise<void> {
    if (!this.pendingToolPayload) return;

    const toolName =
      (this.pendingToolPayload['tool_name'] as string) || 'open-question-form';
    const toolArgs =
      (this.pendingToolPayload['tool_args'] as Record<string, unknown>) || {};

    try {
      const result = await this.mcpService.callTool(
        toolName,
        toolArgs,
        this.currentEndpoint
      );

      const iframe = await this.waitForIframe();
      if (!iframe?.contentWindow) return;

      iframe.contentWindow.postMessage(
        {
          jsonrpc: '2.0',
          method: 'ui/notifications/tool-result',
          params: result,
        },
        '*'
      );
    } catch (e) {
      console.error('[MCP Host] Failed to call tool:', e);
    }
  }

  private waitForIframe(
    retries = 20,
    delayMs = 50
  ): Promise<HTMLIFrameElement | null> {
    return new Promise((resolve) => {
      const check = (attempt: number) => {
        const el = this.mcpFrame?.nativeElement;
        if (el?.contentWindow) {
          resolve(el);
        } else if (attempt < retries) {
          setTimeout(() => check(attempt + 1), delayMs);
        } else {
          resolve(null);
        }
      };
      check(0);
    });
  }

  private async handleToolCall(
    msg: { jsonrpc: string; id: number; params?: any },
    iframe: HTMLIFrameElement
  ): Promise<void> {
    try {
      const result = await this.mcpService.callTool(
        msg.params?.name,
        msg.params?.arguments || {},
        this.currentEndpoint
      );
      const el = this.mcpFrame?.nativeElement ?? iframe;
      el.contentWindow?.postMessage(
        { jsonrpc: '2.0', id: msg.id, result },
        '*'
      );
    } catch (e) {
      const el = this.mcpFrame?.nativeElement ?? iframe;
      el.contentWindow?.postMessage(
        {
          jsonrpc: '2.0',
          id: msg.id,
          error: { code: -32603, message: 'Tool call failed' },
        },
        '*'
      );
    }
  }

  private handleAppMessage(params: any): void {
    const text = params?.content?.[0]?.text || JSON.stringify(params);

    if (this.currentEndpoint.includes('search-app')) {
      try {
        const parsed = JSON.parse(text);
        if (parsed.action === 'select_products') {
          this.chatService.resumeWithData({
            selected_products: parsed.selected_products,
          });
          this.close();
          return;
        }
      } catch {}
      this.chatService.resumeWithData({ cancelled: true });
      this.close();
    } else {
      this.chatService.resumeWithData({ form_data: text, submitted: true });
      this.close();
    }
  }
}
