import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { getHealth, getSession, postChat } from "@/lib/api";
import type { ConversationState, MessageItem } from "@/types/chat";

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
  const session = ref<ConversationState | null>(null);
  const messages = ref<MessageItem[]>([...INITIAL_MESSAGES]);

  const sessionSnapshot = computed(() => ({
    intent: session.value?.current_intent ?? "-",
    stage: session.value?.stage ?? "-",
    clarify: session.value?.needs_clarification ? "yes" : "no",
    slots: session.value?.slots ?? {},
    summary: session.value?.summary || "等待会话开始...",
  }));

  function appendMessage(message: MessageItem) {
    messages.value.push(message);
  }

  async function refreshHealth() {
    try {
      await getHealth();
      backendReady.value = true;
    } catch (error) {
      backendReady.value = false;
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
    statusText.value = "请求处理中...";

    try {
      const response = await postChat({
        session_id: sessionId.value,
        user_id: userId.value.trim() || "user-001",
        channel: channel.value.trim() || "web",
        message,
      });

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

      await refreshSession();
      statusText.value = "发送成功";
    } catch (error) {
      appendMessage({
        id: `error-${Date.now()}`,
        role: "assistant",
        content: "请求失败，请确认 FastAPI 服务是否已启动。",
      });
      statusText.value = "发送失败";
      backendReady.value = false;
    } finally {
      pending.value = false;
      draft.value = "";
    }
  }

  return {
    backendReady,
    channel,
    draft,
    messages,
    pending,
    refreshHealth,
    refreshSession,
    sendMessage,
    sessionId,
    sessionSnapshot,
    statusText,
    userId,
  };
});
