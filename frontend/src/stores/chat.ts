import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { postChat, uploadKnowledgeFile, getKnowledgeFiles, deleteKnowledgeFile, getSessionList, getSessionMessages, updateSession, deleteSession } from "@/lib/api";
import { ChatSSEClient } from "@/lib/sse";
import {
  clearSessionIdFromStorage,
  generateSessionId,
  loadSessionIdFromStorage,
  saveSessionIdToStorage,
} from "@/lib/session";
import type {
  ChatSessionItem,
  ChatSocketEvent,
  ConversationState,
  KnowledgeFileItem,
  MessageItem,
  ToolResult,
  TurnItem,
} from "@/types/chat";

function nowLabel() {
  return new Date().toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function todayLabel() {
  return new Date().toLocaleDateString("zh-CN");
}

function fileSizeLabel(size: number) {
  if (size >= 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (size >= 1024) {
    return `${Math.round(size / 1024)} KB`;
  }
  return `${size} B`;
}

function fileTypeLabel(fileName: string) {
  const extension = fileName.split(".").pop()?.toLowerCase() || "";
  const mapping: Record<string, string> = {
    pdf: "PDF",
    doc: "Word",
    docx: "Word",
    txt: "Text",
    md: "Markdown",
    csv: "CSV",
    xls: "Excel",
    xlsx: "Excel",
    ppt: "PPT",
    pptx: "PPT",
  };
  return mapping[extension] || "File";
}

function createInitialMessage(): MessageItem {
  return {
    id: `assistant-initial-${Date.now()}`,
    role: "assistant",
    content: "你好！我是客服助手，有什么可以帮您的吗？",
  };
}

function createSession(
  title = "新会话",
  sessionId?: string,
  messages?: MessageItem[],
): ChatSessionItem {
  const timestamp = nowLabel();
  const day = todayLabel();
  return {
    id: sessionId || generateSessionId(),
    title,
    createdDay: day,
    createdAt: timestamp,
    updatedDay: day,
    updatedAt: timestamp,
    messages: messages && messages.length ? messages : [createInitialMessage()],
    turns: [],
    session: null,
  };
}

export const useChatStore = defineStore("chat", () => {
  const activePanel = ref<"chat" | "knowledge">("chat");
  const sessions = ref<ChatSessionItem[]>([createSession("客服咨询")]);
  const activeSessionId = ref(sessions.value[0].id);
  const sessionSearch = ref("");
  const channel = ref("web");
  const draft = ref("");
  const knowledgeFiles = ref<KnowledgeFileItem[]>([]);
  const renameDraft = ref("");
  const renamingSessionId = ref<string | null>(null);
  const statusText = ref("等待发送");
  const pending = ref(false);
  const requestStart = ref(0);
  const responseStats = ref({ count: 0, totalMs: 0, lastMs: 0 });
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
      return session.title.toLowerCase().includes(keyword);
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

  const client = new ChatSSEClient({
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
    mainIntent: session.value?.current_main_intent ?? "-",
    subIntent: session.value?.current_sub_intent ?? "-",
    stage: session.value?.stage ?? "-",
    clarify: session.value?.needs_clarification ? "yes" : "no",
    slots: session.value?.slots ?? {},
    missingSlots: session.value?.missing_slots ?? [],
    summary: session.value?.summary || "等待会话开始...",
  }));

  function touchTargetSession(target: ChatSessionItem) {
    target.updatedDay = todayLabel();
    target.updatedAt = nowLabel();
  }

  function touchSession() {
    touchTargetSession(activeSession.value);
  }

  function appendMessage(message: MessageItem) {
    activeSession.value.messages.push(message);
    if (message.role !== "system") {
      touchSession();
    }
  }

  function resetLiveTurn() {
    liveTrace.value = [];
    liveToolResult.value = null;
    liveIntent.value = null;
    liveStage.value = null;
  }

  async function createNewSession() {
    // 会话 id 由前端本地生成（见 @/lib/session），首条消息发到后端后由后端惰性建会话，
    // 不再依赖 /chat/init 的前置往返。
    const newSession = createSession("新会话", generateSessionId());
    sessions.value.unshift(newSession);
    activeSessionId.value = newSession.id;
    saveSessionIdToStorage(newSession.id);
    draft.value = "";
    statusText.value = "已新建会话";
    resetLiveTurn();
  }

  async function fetchKnowledgeFiles() {
    try {
      knowledgeFiles.value = await getKnowledgeFiles();
    } catch (error) {
      console.warn("加载知识库文件失败", error);
    }
  }

  async function uploadKnowledgeFiles(fileList: FileList | null, docType = "markdown") {
    if (!fileList?.length) {
      return;
    }
    const SUPPORTED = [".md", ".markdown", ".json"];
    const MARKDOWN_SUFFIXES = [".md", ".markdown"];
    const JSON_SUFFIXES = [".json"];
    const files = Array.from(fileList);
    const isSupported = (file: File) => {
      const suffix = file.name
        ? file.name.slice(file.name.lastIndexOf(".")).toLowerCase()
        : "";
      if (!file.name || !SUPPORTED.includes(suffix)) {
        return false;
      }
      // 后缀需与所选文档类型一致
      if (docType === "json" && !JSON_SUFFIXES.includes(suffix)) return false;
      if (docType === "markdown" && !MARKDOWN_SUFFIXES.includes(suffix)) return false;
      return true;
    };
    const valid = files.filter(isSupported);
    const invalidCount = files.length - valid.length;

    const results = await Promise.allSettled(
      valid.map((file) => uploadKnowledgeFile(file, docType)),
    );
    const rejectedCount = results.filter((r) => r.status === "rejected").length;
    const okCount = results.filter((r) => r.status === "fulfilled").length;
    const failedCount = rejectedCount + invalidCount;
    statusText.value =
      `已上传 ${okCount} 个文件` +
      (failedCount
        ? `，${failedCount} 个失败（仅支持 .md / .markdown / .json，且后缀需与所选文档类型一致）`
        : "");
    await fetchKnowledgeFiles();
  }

  async function removeKnowledgeFile(id: number) {
    await deleteKnowledgeFile(id);
    knowledgeFiles.value = knowledgeFiles.value.filter((file) => file.id !== id);
    statusText.value = "已删除知识库文件";
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

  async function submitRenameSession(id: string) {
    const target = sessions.value.find((session) => session.id === id);
    const nextTitle = renameDraft.value.trim();
    if (!target || !nextTitle) {
      cancelRenameSession();
      return;
    }
    const trimmed = nextTitle.slice(0, 20);
    target.title = trimmed;
    touchTargetSession(target);
    cancelRenameSession();
    try {
      await updateSession(id, trimmed);
    } catch (error) {
      // 后端不可用时静默忽略，前端标题已更新
    }
  }

  async function removeSession(id: string) {
    try {
      await deleteSession(id);
    } catch (error) {
      // 纯本地会话后端可能不存在，忽略
    }
    sessions.value = sessions.value.filter((session) => session.id !== id);
    if (sessions.value.length === 0) {
      await createNewSession();
    } else if (!sessions.value.some((session) => session.id === activeSessionId.value)) {
      activeSessionId.value = sessions.value[0].id;
    }
    statusText.value = "已删除会话";
  }

  async function renameSessionDirect(id: string, title: string) {
    const trimmed = title.trim().slice(0, 20);
    if (!trimmed) {
      return;
    }
    const target = sessions.value.find((session) => session.id === id);
    if (target) {
      target.title = trimmed;
      touchTargetSession(target);
    }
    try {
      await updateSession(id, trimmed);
    } catch (error) {
      // 后端不可用时保留本地标题
    }
  }

  async function switchSession(id: string) {
    activeSessionId.value = id;
    draft.value = "";
    statusText.value = "已切换会话";
    resetLiveTurn();

    // 懒加载历史消息：仅当会话只有初始问候或为空时从后端回放
    const msgs = activeSession.value.messages;
    const onlyGreeting = msgs.length === 1 && msgs[0].id.startsWith("assistant-initial");
    if (msgs.length === 0 || onlyGreeting) {
      try {
        const history = await getSessionMessages(id);
        if (history.length) {
          activeSession.value.messages = history;
        }
      } catch (error) {
        // 后端不可用时保留本地消息
      }
    }
  }

  async function loadSessions() {
    const list = await getSessionList();
    sessions.value = list.map((s) =>
      createSession(s.title || "新会话", s.session_id),
    );
  }

  async function initFromLocalStorage() {
    const savedSessionId = loadSessionIdFromStorage();
    try {
      await loadSessions();
      if (sessions.value.length) {
        if (savedSessionId && sessions.value.some((s) => s.id === savedSessionId)) {
          await switchSession(savedSessionId);
        } else {
          activeSessionId.value = sessions.value[0].id;
        }
        statusText.value = "已加载历史会话";
      } else {
        await createNewSession();
        statusText.value = "已新建会话";
      }
    } catch (error) {
      // 后端不可用：退回新建会话，本地缓存的旧 session_id 直接清掉。
      clearSessionIdFromStorage();
      statusText.value = "后端不可用，已新建会话";
      await createNewSession();
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
      liveIntent.value = `${event.main_intent} / ${event.sub_intent}`;
      liveTrace.value.push(
        `识别主意图=${event.main_intent}，子意图=${event.sub_intent}，clarify=${event.needs_clarification}，slots=${JSON.stringify(event.slots)}`,
      );
      return;
    }

    if (event.type === "state") {
      liveStage.value = event.stage;
      liveTrace.value.push(
        `进入阶段=${event.stage}，主意图=${event.current_main_intent}，子意图=${event.current_sub_intent}，missing_slots=${JSON.stringify(event.missing_slots)}`,
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
      const ss = response.session_state;
      appendMessage({
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: response.reply,
      });
      activeSession.value.session = response.session_state;
      activeSession.value.turns.unshift({
        id: `turn-${Date.now()}`,
        mainIntent: ss.current_main_intent,
        subIntent: ss.current_sub_intent,
        stage: ss.stage,
        summary: ss.summary,
        trace: [...liveTrace.value],
        toolResult: liveToolResult.value,
        createdAt: new Date().toLocaleTimeString("zh-CN", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }),
      });
      touchSession();
      const cost = requestStart.value ? Date.now() - requestStart.value : 0;
      responseStats.value = {
        count: responseStats.value.count + 1,
        totalMs: responseStats.value.totalMs + cost,
        lastMs: cost,
      };
      const avg = Math.round(responseStats.value.totalMs / responseStats.value.count);
      console.info(
        `[chat] 发送成功 响应时间=${cost}ms 平均=${avg}ms 次数=${responseStats.value.count}`,
      );
      statusText.value = `发送成功 (响应时间: ${cost} ms)`;
      pending.value = false;
      draft.value = "";
      resetLiveTurn();
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
    // 当前会话的最新状态由 SSE final 事件回填，刷新按钮无需再拉后端。
    touchSession();
    statusText.value = "状态已刷新";
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
    requestStart.value = Date.now();
    resetLiveTurn();

    try {
      await client.send({
        session_id: sessionId.value,
        channel: channel.value.trim() || "web",
        message,
      });
    } catch (error) {
      pending.value = false;
      backendReady.value = false;
      liveTrace.value.push("SSE 连接失败，回退到 HTTP /chat");
      try {
        const response = await postChat({
          session_id: sessionId.value,
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
    activePanel,
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
    responseStats,
    refreshSession,
    knowledgeFiles,
    removeKnowledgeFile,
    fetchKnowledgeFiles,
    removeSession,
    renameSessionDirect,
    renameDraft,
    renamingSessionId,
    sendMessage,
    sessionId,
    sessionSearch,
    sessionSnapshot,
    sessions,
    startRenameSession,
    groupedSessions,
    initFromLocalStorage,
    socketConnected,
    statusText,
    submitRenameSession,
    switchSession,
    turns,
    uploadKnowledgeFiles,
  };
});
