export type MainIntentCode =
  | "faq"
  | "order_service"
  | "logistics_service"
  | "refund_service"
  | "handoff_service"
  | "chitchat"
  | "unsupported";

export type SubIntentCode =
  | "faq.general"
  | "order_service.query_status"
  | "logistics_service.query_status"
  | "refund_service.consult_policy"
  | "refund_service.request_refund"
  | "handoff_service.request_human"
  | "chitchat.greeting"
  | "chitchat.thanks"
  | "unsupported.unknown";

export interface EmotionState {
  primary: "neutral" | "confused" | "anxious" | "angry" | "urgent" | "happy";
  confidence: number;
  trend: "stable" | "escalating" | "deescalating";
}

export interface ActionRecord {
  action_name: string;
  status: string;
  summary: string;
  created_at: string;
}

export interface ChatRequest {
  session_id: string;
  user_id: string;
  message: string;
  channel: string;
}

export interface ChatResponse {
  reply: string;
  main_intent: MainIntentCode;
  sub_intent: SubIntentCode;
  stage: string;
  needs_clarification: boolean;
  handoff: boolean;
  slots: Record<string, string>;
  missing_slots: string[];
  summary: string;
  emotion: EmotionState;
  current_action: string;
  running_summary: string;
  tool_result: ToolResult | null;
  session_state: ConversationState;
  turn_trace: string[];
}

export interface ConversationState {
  session_id: string;
  user_id: string;
  channel: string;
  current_main_intent: MainIntentCode;
  current_sub_intent: SubIntentCode;
  stage: string;
  slots: Record<string, string>;
  missing_slots: string[];
  confirmed_slots?: string[];
  candidate_intents?: string[];
  risk_level: "low" | "medium" | "high";
  emotion?: EmotionState;
  needs_clarification: boolean;
  topic_changed?: boolean;
  current_action?: string;
  latest_action_name?: string;
  latest_action_result?: Record<string, unknown> | null;
  action_history?: ActionRecord[];
  summary: string;
  running_summary?: string;
  message_history: Array<Record<string, string>>;
  recent_messages?: Array<Record<string, string>>;
  last_user_message: string;
  handoff: boolean;
  handoff_reason?: string;
  reply: string;
  archived_states?: Array<Record<string, unknown>>;
}

export interface OrderToolData {
  order_id: string;
  status: string;
  product_name: string;
  amount: number;
}

export interface LogisticsEvent {
  time: string;
  status: string;
}

export interface LogisticsToolData {
  order_id: string;
  tracking_status: string;
  timeline: LogisticsEvent[];
}

export interface HandoffToolData {
  ticket_id: string;
  summary: string;
}

export interface KnowledgeToolData {
  faq_key: string;
  question: string;
  answer: string;
  score: number;
  doc_type: string;
}

export interface ToolResult {
  kind: "knowledge" | "order" | "logistics" | "handoff";
  raw_result?: Record<string, unknown> | null;
  sanitized_result?:
    | OrderToolData
    | LogisticsToolData
    | HandoffToolData
    | KnowledgeToolData
    | null;
  user_facing_summary?: string;
}

export interface MessageItem {
  id: string;
  role: "assistant" | "user" | "system";
  content: string;
  tone?: "normal" | "meta";
}

export interface TurnItem {
  id: string;
  mainIntent: MainIntentCode;
  subIntent: SubIntentCode;
  stage: string;
  summary: string;
  trace: string[];
  toolResult: ToolResult | null;
  createdAt: string;
}

export interface ChatSessionItem {
  id: string;
  title: string;
  preview: string;
  createdDay: string;
  createdAt: string;
  updatedDay: string;
  updatedAt: string;
  messages: MessageItem[];
  turns: TurnItem[];
  session: ConversationState | null;
}

export interface ChatSocketStatusEvent {
  type: "status";
  stage: string;
  message: string;
}

export interface ChatSocketIntentEvent {
  type: "intent";
  main_intent: MainIntentCode;
  sub_intent: SubIntentCode;
  confidence: number;
  slots: Record<string, string>;
  needs_clarification: boolean;
}

export interface ChatSocketStateEvent {
  type: "state";
  stage: string;
  current_main_intent: MainIntentCode;
  current_sub_intent: SubIntentCode;
  slots: Record<string, string>;
  missing_slots: string[];
  needs_clarification: boolean;
}

export interface ChatSocketTraceEvent {
  type: "trace";
  message: string;
}

export interface ChatSocketToolResultEvent {
  type: "tool_result";
  tool_result: ToolResult | null;
}

export interface ChatSocketFinalEvent {
  type: "final";
  response: ChatResponse;
}

export interface ChatSocketErrorEvent {
  type: "error";
  message: string;
}

export type ChatSocketEvent =
  | ChatSocketStatusEvent
  | ChatSocketIntentEvent
  | ChatSocketStateEvent
  | ChatSocketTraceEvent
  | ChatSocketToolResultEvent
  | ChatSocketFinalEvent
  | ChatSocketErrorEvent;
