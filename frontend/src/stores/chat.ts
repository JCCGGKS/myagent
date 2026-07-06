import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { getHealth, getSession, postChat } from "@/lib/api";
import { ChatWebSocketClient } from "@/lib/websocket";
import type {
  ChatSocketEvent,
  ConversationState,
  MessageItem,
  ToolResult,
  TurnItem,
} from "@/types/chat";

const SESSION_ID = `web-${Date.now()}`;

const INITIAL_MESSAGES: MessageItem[] = [
  {
    id: "assistant-initial",
    role: "assistant",
    content: "输入一个问题开始演示。支持 FAQ、订单查询、物流查询和转人工。",
  },
];

export const useChatStore = defineStore("chat", () => {
  const sessionId = ref(SESSION_ID);
  const userId = ref("user-001");
  const channel = ref("web");
  const draft = ref("");
  const statusText = ref("等待发送");
  const pending = ref(false);
  const backendReady = ref<boolean | null>(null);
  const socketConnected = ref(false);
  const session = ref<ConversationState | null>(null);
  const messages = ref<MessageItem[]>([...INITIAL_MESSAGES]);
  const turns = ref<TurnItem[]>([]);
  const liveTrace = ref<string[]>([]);
  const liveToolResult = ref<ToolResult | null>(null);
  const liveIntent = ref<string | null>(null);
  const liveStage = ref<string | null>(null);

  const client = new ChatWebSocketClient({
    onEvent: handleSocketEvent,
    onOpenChange: (connected) => {
      socketConnected.value = connected;
      backendReady.value = connected;
    },
  });

  const sessionSnapshot = computed(() => ({
    intent: session.value?.current_intent ?? "-",
    stage: session.value?.stage ?? "-",
    clarify: session.value?.needs_clarification ? "yes" : "no",
    slots: session.value?.slots ?? {},
    missingSlots: session.value?.missing_slots ?? [],
    summary: session.value?.summary || "等待会话开始...",
  }));

  function appendMessage(message: MessageItem) {
    messages.value.push(message);
  }

  function resetLiveTurn() {
    liveTrace.value = [];
    liveToolResult.value = null;
    liveIntent.value = null;
    liveStage.value = null;
  }

  function handleSocketEvent(event: ChatSocketEvent) {
    if (event.type === "status") {
      liveStage.value = event.stage;
      liveTrace.value.push(event.message);
      statusText.value = event.message;
      return;
    }

    if (event.type === "intent") {
      liveIntent.value = event.intent;
      liveTrace.value.push(
        `识别意图=${event.intent}，clarify=${event.needs_clarification}，slots=${JSON.stringify(event.slots)}`,
      );
      return;
    }

    if (event.type === "state") {
      liveStage.value = event.stage;
      liveTrace.value.push(
        `进入阶段=${event.stage}，missing_slots=${JSON.stringify(event.missing_slots)}`,
      );
      return;
    }

    if (event.type === "trace") {
      liveTrace.value.push(event.message);
      return;
    }

    if (event.type === "tool_result") {
      liveToolResult.value = event.tool_result;
      if (event.tool_result?.kind) {
        liveTrace.value.push(`工具执行完成: ${event.tool_result.kind}`);
      }
      return;
    }

    if (event.type === "error") {
      appendMessage({
        id: `error-${Date.now()}`,
        role: "assistant",
        content: event.message,
      });
      statusText.value = "发送失败";
      pending.value = false;
      backendReady.value = false;
      return;
    }

    if (event.type === "final") {
      const response = event.response;
      appendMessage({
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: response.reply,
      });
      appendMessage({
        id: `system-${Date.now()}`,
        role: "system",
        tone: "meta",
        content: `intent=${response.intent} | stage=${response.stage} | clarify=${response.needs_clarification} | slots=${JSON.stringify(response.slots)}`,
      });
      session.value = response.session_state;
      turns.value.unshift({
        id: `turn-${Date.now()}`,
        intent: response.intent,
        stage: response.stage,
        summary: response.summary,
        trace: [...liveTrace.value, ...response.turn_trace],
        toolResult: liveToolResult.value ?? response.tool_result,
        createdAt: new Date().toLocaleTimeString("zh-CN", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }),
      });
      statusText.value = "发送成功";
      pending.value = false;
      draft.value = "";
      resetLiveTurn();
    }
  }

  async function refreshHealth() {
    try {
      await getHealth();
      backendReady.value = true;
    } catch (error) {
      backendReady.value = false;
    }
  }

  async function connectSocket() {
    try {
      await client.connect();
    } catch (error) {
      socketConnected.value = false;
    }
  }

  async function refreshSession() {
    try {
      session.value = await getSession(sessionId.value);
      statusText.value = "状态已刷新";
    } catch (error) {
      statusText.value = "当前还没有会话状态";
    }
  }

  async function sendMessage(rawMessage?: string) {
    const message = (rawMessage ?? draft.value).trim();
    if (!message || pending.value) {
      return;
    }

    appendMessage({
      id: `user-${Date.now()}`,
      role: "user",
      content: message,
    });

    pending.value = true;
    statusText.value = "WebSocket 请求处理中...";
    resetLiveTurn();

    try {
      await client.send({
        session_id: sessionId.value,
        user_id: userId.value.trim() || "user-001",
        channel: channel.value.trim() || "web",
        message,
      });
    } catch (error) {
      pending.value = false;
      backendReady.value = false;
      liveTrace.value.push("WebSocket 连接失败，回退到 HTTP /chat");
      try {
        const response = await postChat({
          session_id: sessionId.value,
          user_id: userId.value.trim() || "user-001",
          channel: channel.value.trim() || "web",
          message,
        });
        handleSocketEvent({ type: "final", response });
      } catch (fallbackError) {
        appendMessage({
          id: `error-${Date.now()}`,
          role: "assistant",
          content: "请求失败，请确认 FastAPI 服务是否已启动。",
        });
        statusText.value = "发送失败";
      }
    }
  }

  return {
    backendReady,
    channel,
    draft,
    liveIntent,
    liveStage,
    liveToolResult,
    liveTrace,
    messages,
    pending,
    connectSocket,
    refreshHealth,
    refreshSession,
    sendMessage,
    sessionId,
    sessionSnapshot,
    socketConnected,
    statusText,
    turns,
    userId,
  };
});
