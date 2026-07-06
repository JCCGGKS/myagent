export type IntentCode =
  | "faq"
  | "query_order"
  | "query_logistics"
  | "handoff_human"
  | "unsupported";

export interface ChatRequest {
  session_id: string;
  user_id: string;
  message: string;
  channel: string;
}

export interface ChatResponse {
  reply: string;
  intent: IntentCode;
  stage: string;
  needs_clarification: boolean;
  handoff: boolean;
  slots: Record<string, string>;
}

export interface ConversationState {
  session_id: string;
  user_id: string;
  channel: string;
  current_intent: IntentCode;
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

export interface MessageItem {
  id: string;
  role: "assistant" | "user" | "system";
  content: string;
  tone?: "normal" | "meta";
}
