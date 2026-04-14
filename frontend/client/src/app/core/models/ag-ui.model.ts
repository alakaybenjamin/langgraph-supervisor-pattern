/**
 * AG-UI (Agent-User Interaction) protocol event types and request/response
 * models consumed by the Angular frontend.
 *
 * Field names use camelCase to match the AG-UI wire format produced by the
 * Python ``EventEncoder``.
 */

export enum AgUiEventType {
  RUN_STARTED = 'RUN_STARTED',
  RUN_FINISHED = 'RUN_FINISHED',
  RUN_ERROR = 'RUN_ERROR',
  STEP_STARTED = 'STEP_STARTED',
  STEP_FINISHED = 'STEP_FINISHED',
  TEXT_MESSAGE_START = 'TEXT_MESSAGE_START',
  TEXT_MESSAGE_CONTENT = 'TEXT_MESSAGE_CONTENT',
  TEXT_MESSAGE_END = 'TEXT_MESSAGE_END',
  STATE_SNAPSHOT = 'STATE_SNAPSHOT',
  STATE_DELTA = 'STATE_DELTA',
  CUSTOM = 'CUSTOM',
}

export interface BaseAgUiEvent {
  type: AgUiEventType;
  timestamp?: number;
}

export interface RunStartedEvent extends BaseAgUiEvent {
  type: AgUiEventType.RUN_STARTED;
  threadId: string;
  runId: string;
}

export interface RunFinishedEvent extends BaseAgUiEvent {
  type: AgUiEventType.RUN_FINISHED;
  threadId: string;
  runId: string;
}

export interface RunErrorEvent extends BaseAgUiEvent {
  type: AgUiEventType.RUN_ERROR;
  message: string;
  code?: string;
}

export interface StepStartedEvent extends BaseAgUiEvent {
  type: AgUiEventType.STEP_STARTED;
  stepName: string;
}

export interface StepFinishedEvent extends BaseAgUiEvent {
  type: AgUiEventType.STEP_FINISHED;
  stepName: string;
}

export interface TextMessageStartEvent extends BaseAgUiEvent {
  type: AgUiEventType.TEXT_MESSAGE_START;
  messageId: string;
  role: 'assistant' | 'user' | 'system' | 'developer';
}

export interface TextMessageContentEvent extends BaseAgUiEvent {
  type: AgUiEventType.TEXT_MESSAGE_CONTENT;
  messageId: string;
  delta: string;
}

export interface TextMessageEndEvent extends BaseAgUiEvent {
  type: AgUiEventType.TEXT_MESSAGE_END;
  messageId: string;
}

export interface StateSnapshotEvent extends BaseAgUiEvent {
  type: AgUiEventType.STATE_SNAPSHOT;
  snapshot: unknown;
}

export interface StateDeltaEvent extends BaseAgUiEvent {
  type: AgUiEventType.STATE_DELTA;
  delta: unknown[];
}

export interface CustomAgUiEvent extends BaseAgUiEvent {
  type: AgUiEventType.CUSTOM;
  name: string;
  value: unknown;
}

export type AgUiEvent =
  | RunStartedEvent
  | RunFinishedEvent
  | RunErrorEvent
  | StepStartedEvent
  | StepFinishedEvent
  | TextMessageStartEvent
  | TextMessageContentEvent
  | TextMessageEndEvent
  | StateSnapshotEvent
  | StateDeltaEvent
  | CustomAgUiEvent;

/** AG-UI message role union used in RunAgentInput. */
export interface AgUiMessage {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'developer';
  content: string;
}

/**
 * Body sent to POST /ag-ui.
 *
 * Uses snake_case for the *request* because the FastAPI Pydantic model
 * ``RunAgentInput`` expects snake_case fields.
 */
export interface RunAgentInput {
  thread_id: string;
  run_id: string;
  messages: AgUiMessage[];
  tools: unknown[];
  state: unknown;
  context: unknown[];
  forwarded_props: unknown;
}
