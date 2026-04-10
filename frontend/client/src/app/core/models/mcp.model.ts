export interface McpAppPayload {
  resource_uri: string;
  mcp_endpoint: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  context?: Record<string, unknown>;
}
