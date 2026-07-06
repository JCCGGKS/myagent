export type MainIntentCode =
  | "faq"
  | "order_service"
  | "logistics_service"
  | "handoff_service"
  | "chitchat"
  | "unsupported";

export type SubIntentCode =
  | "faq.general"
  | "order_service.query_status"
  | "logistics_service.query_status"
  | "handoff_service.request_human"
  | "chitchat.greeting"
  | "unsupported.unknown";

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
  risk_level: "low" | "medium" | "high";
  needs_clarification: boolean;
  summary: string;
  message_history: Array<Record<string, string>>;
  last_user_message: string;
  handoff: boolean;
  reply: string;
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

export interface ToolResult {
  kind: "order" | "logistics" | "handoff";
  data: OrderToolData | LogisticsToolData | HandoffToolData | null;
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
