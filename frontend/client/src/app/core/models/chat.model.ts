export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  interrupt?: InterruptPayload;
}

export interface ChatRequest {
  action: 'send' | 'resume';
  message?: string;
  resume_data?: Record<string, unknown>;
  thread_id: string;
  user_id: string;
}

export interface InterruptPayload {
  type: string;
  interrupt_value: Record<string, unknown>;
  thread_id: string;
}

export interface SSETokenEvent {
  token: string;
}

export interface SSEDoneEvent {
  type: 'message';
  content: string;
  thread_id: string;
}

export interface SSEInterruptEvent {
  type: 'interrupt';
  interrupt_value: Record<string, unknown>;
  thread_id: string;
}

export interface SSEErrorEvent {
  type: 'error';
  content: string;
}
