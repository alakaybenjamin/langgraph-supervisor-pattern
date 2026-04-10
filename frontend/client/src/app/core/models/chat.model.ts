export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  interrupt?: InterruptPayload;
}

export interface ChatRequest {
  message: string;
  thread_id: string;
  user_id: string;
}

export interface ChatResumeRequest {
  resume_data: Record<string, unknown>;
  thread_id: string;
  user_id: string;
}

export interface InterruptPayload {
  type: string;
  interrupt_value: Record<string, unknown>;
  thread_id: string;
}

export interface ChatResponse {
  type: 'message' | 'interrupt' | 'error';
  content: string;
  thread_id: string;
  interrupt?: InterruptPayload | null;
}
