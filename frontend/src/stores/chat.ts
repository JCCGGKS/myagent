import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { getHealth, getSession, postChat } from "@/lib/api";
import { ChatWebSocketClient } from "@/lib/websocket";
import type {
  ChatSessionItem,
  ChatSocketEvent,
  ConversationState,
  MessageItem,
  ToolResult,
  TurnItem,
} from "@/types/chat";

function createSessionId() {
  return `web-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function nowLabel() {
  return new Date().toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function todayLabel() {
  return new Date().toLocaleDateString("zh-CN");
}

function createInitialMessage(): MessageItem {
  return {
    id: `assistant-initial-${Date.now()}`,
    role: "assistant",
    content: "输入一个问题开始演示。支持 FAQ、订单查询、物流查询和转人工。",
  };
}

function createSession(title = "新会话"): ChatSessionItem {
  const timestamp = nowLabel();
  const day = todayLabel();
  return {
    id: createSessionId(),
    title,
    preview: "等待开始对话",
    createdDay: day,
    createdAt: timestamp,
    updatedDay: day,
    updatedAt: timestamp,
    messages: [createInitialMessage()],
    turns: [],
    session: null,
  };
}

export const useChatStore = defineStore("chat", () => {
  const sessions = ref<ChatSessionItem[]>([createSession("客服咨询")]);
  const activeSessionId = ref(sessions.value[0].id);
  const sessionSearch = ref("");
  const userId = ref("user-001");
  const channel = ref("web");
  const draft = ref("");
  const renameDraft = ref("");
  const renamingSessionId = ref<string | null>(null);
  const statusText = ref("等待发送");
  const pending = ref(false);
  const backendReady = ref<boolean | null>(null);
  const socketConnected = ref(false);
  const liveTrace = ref<string[]>([]);
  const liveToolResult = ref<ToolResult | null>(null);
  const liveIntent = ref<string | null>(null);
  const liveStage = ref<string | null>(null);

  const activeSession = computed(
    () => sessions.value.find((session) => session.id === activeSessionId.value) ?? sessions.value[0],
  );
  const filteredSessions = computed(() => {
    const keyword = sessionSearch.value.trim().toLowerCase();
    if (!keyword) {
      return sessions.value;
    }
    return sessions.value.filter((session) => {
      return `${session.title} ${session.preview}`.toLowerCase().includes(keyword);
    });
  });
  const groupedSessions = computed(() => {
    const groups: Array<{ label: string; items: ChatSessionItem[] }> = [];
    const today = todayLabel();
    const todayItems = filteredSessions.value.filter((session) => session.updatedDay === today);
    const olderItems = filteredSessions.value.filter(
      (session) => !todayItems.some((item) => item.id === session.id),
    );
    if (todayItems.length) {
      groups.push({ label: "今天", items: todayItems });
    }
    if (olderItems.length) {
      groups.push({ label: "更早", items: olderItems });
    }
    return groups;
  });

  const client = new ChatWebSocketClient({
    onEvent: handleSocketEvent,
    onOpenChange: (connected) => {
      socketConnected.value = connected;
      backendReady.value = connected;
    },
  });

  const sessionId = computed(() => activeSession.value.id);
  const messages = computed(() => activeSession.value.messages);
  const turns = computed(() => activeSession.value.turns);
  const session = computed(() => activeSession.value.session);

  const sessionSnapshot = computed(() => ({
    intent: session.value?.current_intent ?? "-",
    stage: session.value?.stage ?? "-",
    clarify: session.value?.needs_clarification ? "yes" : "no",
    slots: session.value?.slots ?? {},
    missingSlots: session.value?.missing_slots ?? [],
    summary: session.value?.summary || "等待会话开始...",
  }));

  function touchTargetSession(target: ChatSessionItem, preview?: string) {
    target.updatedDay = todayLabel();
    target.updatedAt = nowLabel();
    if (preview) {
      target.preview = preview;
    }
  }

  function touchSession(preview?: string) {
    touchTargetSession(activeSession.value, preview);
  }

  function appendMessage(message: MessageItem) {
    activeSession.value.messages.push(message);
    if (message.role !== "system") {
      touchSession(message.content);
    }
  }

  function resetLiveTurn() {
    liveTrace.value = [];
    liveToolResult.value = null;
    liveIntent.value = null;
    liveStage.value = null;
  }

  function createNewSession() {
    const newSession = createSession();
    sessions.value.unshift(newSession);
    activeSessionId.value = newSession.id;
    draft.value = "";
    statusText.value = "已新建会话";
    resetLiveTurn();
  }

  function startRenameSession(id: string) {
    const target = sessions.value.find((session) => session.id === id);
    if (!target) {
      return;
    }
    renamingSessionId.value = id;
    renameDraft.value = target.title;
  }

  function cancelRenameSession() {
    renamingSessionId.value = null;
    renameDraft.value = "";
  }

  function submitRenameSession(id: string) {
    const target = sessions.value.find((session) => session.id === id);
    const nextTitle = renameDraft.value.trim();
    if (!target || !nextTitle) {
      cancelRenameSession();
      return;
    }
    target.title = nextTitle.slice(0, 20);
    touchTargetSession(target, target.preview);
    cancelRenameSession();
  }

  function removeSession(id: string) {
    if (sessions.value.length === 1) {
      createNewSession();
    }
    sessions.value = sessions.value.filter((session) => session.id !== id);
    if (!sessions.value.some((session) => session.id === activeSessionId.value)) {
      activeSessionId.value = sessions.value[0].id;
    }
    statusText.value = "已删除会话";
  }

  async function switchSession(id: string) {
    activeSessionId.value = id;
    draft.value = "";
    statusText.value = "已切换会话";
    resetLiveTurn();

    if (!activeSession.value.session) {
      try {
        activeSession.value.session = await getSession(id);
      } catch (error) {
        // Ignore 404 for brand new local sessions.
      }
    }
  }

  function updateSessionTitle(message: string) {
    if (activeSession.value.title === "新会话" || activeSession.value.title === "客服咨询") {
      activeSession.value.title = message.slice(0, 12) || "新会话";
    }
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
      activeSession.value.session = response.session_state;
      activeSession.value.turns.unshift({
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
      touchSession(response.reply);
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
      activeSession.value.session = await getSession(sessionId.value);
      touchSession(activeSession.value.preview);
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

    updateSessionTitle(message);
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
    activeSession,
    activeSessionId,
    backendReady,
    cancelRenameSession,
    channel,
    connectSocket,
    createNewSession,
    draft,
    liveIntent,
    liveStage,
    liveToolResult,
    liveTrace,
    messages,
    pending,
    refreshHealth,
    refreshSession,
    removeSession,
    renameDraft,
    renamingSessionId,
    sendMessage,
    sessionId,
    sessionSearch,
    sessionSnapshot,
    sessions,
    startRenameSession,
    groupedSessions,
    socketConnected,
    statusText,
    submitRenameSession,
    switchSession,
    turns,
    userId,
  };
});
