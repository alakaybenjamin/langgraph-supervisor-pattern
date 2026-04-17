/**
 * Chat / stream / interrupt model types.
 *
 * The `InterruptValue` discriminated union mirrors the backend's TypedDict
 * union in `backend/app/graph/state.py`. Keeping these in lock-step gives
 * the frontend type-safe narrowing (see `isInterrupt` in the message
 * component) and kills the previous `Record<string, unknown>` casts.
 */

// ---------------------------------------------------------------------------
// Chat messages
// ---------------------------------------------------------------------------

export type ChatRole = 'user' | 'assistant' | 'system';

export interface ChatMessage {
  role: ChatRole;
  content: string;
  timestamp: Date;
  interrupt?: InterruptPayload;
}

// ---------------------------------------------------------------------------
// Request / SSE envelopes
// ---------------------------------------------------------------------------

export interface ChatRequest {
  action: 'send' | 'resume';
  message?: string;
  resume_data?: Record<string, unknown>;
  thread_id: string;
  user_id: string;
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
  interrupt_value: InterruptValue;
  thread_id: string;
}

export interface SSEErrorEvent {
  type: 'error';
  content: string;
}

// ---------------------------------------------------------------------------
// Interrupt payload — discriminated union
// ---------------------------------------------------------------------------

/** Shared fields on every interrupt value. */
interface InterruptBase {
  message?: string;
  step: string;
  prompt_id?: string;
}

export interface FacetSelectionInterrupt extends InterruptBase {
  type: 'facet_selection';
  facet: string;
  options: FacetOption[];
}

export interface ProductSelectionInterrupt extends InterruptBase {
  type: 'product_selection';
  products: Product[];
  allow_search?: boolean;
  allow_multi_select?: boolean;
}

export interface CartReviewInterrupt extends InterruptBase {
  type: 'cart_review';
  products: Product[];
  actions: ActionButton[];
}

export interface ConfirmationInterrupt extends InterruptBase {
  type: 'confirmation';
  products?: Product[];
  form_data?: Record<string, unknown>;
  products_summary?: string;
  actions?: ActionButton[];
}

export interface McpAppInterrupt extends InterruptBase {
  type: 'mcp_app';
  resource_uri: string;
  mcp_endpoint?: string;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  context?: Record<string, unknown>;
}

export type InterruptValue =
  | FacetSelectionInterrupt
  | ProductSelectionInterrupt
  | CartReviewInterrupt
  | ConfirmationInterrupt
  | McpAppInterrupt;

export type InterruptType = InterruptValue['type'];

/** Narrow an InterruptValue by discriminator. */
export type InterruptOf<T extends InterruptType> = Extract<
  InterruptValue,
  { type: T }
>;

/** Required-field contract per interrupt type, enforced in `ChatService`. */
export const INTERRUPT_REQUIRED_FIELDS: {
  readonly [K in InterruptType]: readonly (keyof InterruptOf<K>)[];
} = {
  facet_selection: ['type', 'facet', 'options', 'step'],
  product_selection: ['type', 'products', 'step'],
  cart_review: ['type', 'products', 'actions', 'step'],
  confirmation: ['type', 'step'],
  mcp_app: ['type', 'resource_uri', 'step'],
} as const;

/**
 * Discriminated-union guard. Returns the narrowed interrupt value if its
 * `type` matches and required fields are present; otherwise `null`.
 *
 * This is the frontend equivalent of the LangChain docs' recommended
 * `extractStructuredOutput<T>(messages, requiredFields)` helper.
 */
export function asInterrupt<T extends InterruptType>(
  value: unknown,
  type: T,
): InterruptOf<T> | null {
  if (!value || typeof value !== 'object') return null;
  const v = value as { type?: unknown };
  if (v.type !== type) return null;
  const required = INTERRUPT_REQUIRED_FIELDS[type] as readonly string[];
  for (const f of required) {
    if ((v as Record<string, unknown>)[f] === undefined) return null;
  }
  return v as InterruptOf<T>;
}

/**
 * Looser guard — only checks `type`, not required fields. Useful for
 * routing when you want to know which branch to take even if the payload
 * is partial (e.g. during streaming).
 */
export function hasInterruptType<T extends InterruptType>(
  value: unknown,
  type: T,
): value is InterruptOf<T> {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as { type?: unknown }).type === type
  );
}

// ---------------------------------------------------------------------------
// Shared sub-schemas
// ---------------------------------------------------------------------------

export interface FacetOption {
  id: string;
  label: string;
}

export interface ActionButton {
  id: string;
  label: string;
}

export interface ProductMetadata {
  id?: string;
  product_type?: string;
  domain?: string;
  sensitivity?: string;
  [key: string]: unknown;
}

export interface Product {
  content: string;
  metadata?: ProductMetadata;
}

/**
 * Outer wrapper stored on a ChatMessage. Keeps the thread_id tied to the
 * payload so the frontend can reconstruct state if the server and client
 * diverge on thread ids.
 */
export interface InterruptPayload {
  interrupt_value: InterruptValue;
  thread_id: string;
}

// ---------------------------------------------------------------------------
// `useStream`-shaped input
// ---------------------------------------------------------------------------

/**
 * Input accepted by `stream.submit(...)`, modeled after the LangChain
 * `useStream` docs. Exactly one of `messages` or `resume` is expected on
 * any given call.
 */
export interface StreamSubmitInput {
  messages?: Array<{ type: 'human'; content: string }>;
  resume?: Record<string, unknown>;
}
