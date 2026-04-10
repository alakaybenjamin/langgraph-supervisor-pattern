import { Injectable, signal } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

const MCP_HEADERS = new HttpHeaders({
  'Content-Type': 'application/json',
  Accept: 'application/json',
});

@Injectable({ providedIn: 'root' })
export class McpService {
  mcpHtml = signal<string | null>(null);
  loading = signal<boolean>(false);

  private activeEndpoint = '/mcp/question-form';

  constructor(private http: HttpClient) {}

  setEndpoint(endpoint: string): void {
    this.activeEndpoint = endpoint;
  }

  async fetchAppHtml(resourceUri: string, endpoint?: string): Promise<string> {
    const url = endpoint || this.activeEndpoint;
    this.loading.set(true);
    try {
      const body = {
        jsonrpc: '2.0',
        id: 1,
        method: 'resources/read',
        params: { uri: resourceUri },
      };
      const resp: any = await firstValueFrom(
        this.http.post(url, body, { headers: MCP_HEADERS })
      );

      const contents = resp?.result?.contents;
      if (contents && contents.length > 0) {
        const html = contents[0].text || contents[0].content || '';
        this.mcpHtml.set(html);
        return html;
      }
      throw new Error('No content in MCP response');
    } finally {
      this.loading.set(false);
    }
  }

  async callTool(
    toolName: string,
    args: Record<string, unknown>,
    endpoint?: string
  ): Promise<any> {
    const url = endpoint || this.activeEndpoint;
    const body = {
      jsonrpc: '2.0',
      id: 2,
      method: 'tools/call',
      params: { name: toolName, arguments: args },
    };
    const resp: any = await firstValueFrom(
      this.http.post(url, body, { headers: MCP_HEADERS })
    );
    return resp?.result;
  }

  clear(): void {
    this.mcpHtml.set(null);
  }
}
