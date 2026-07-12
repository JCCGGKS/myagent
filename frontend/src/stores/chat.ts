import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { postChat, uploadKnowledgeFile, getKnowledgeFiles, deleteKnowledgeFile, getSessionList, getSessionMessages, updateSession, deleteSession } from "@/lib/api";
import { ChatSSEClient } from "@/lib/sse";
import {
  clearSessionIdFromStorage,
  clearSessionMessages,
  generateSessionId,
  loadSessionIdFromStorage,
  loadSessionMessages,
  saveSessionIdToStorage,
  saveSessionMessages,
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
      saveSessionMessages(activeSession.value.id, activeSession.value.messages);
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

  interface UploadSummary {
    okCount: number;
    failedCount: number;
    // 后缀不支持或与所选文档类型不一致而被本地跳过的文件名
    invalidNames: string[];
    // 服务端拒绝 / 网络错误的可读信息
    serverErrors: string[];
  }

  async function uploadKnowledgeFiles(
    fileList: FileList | null,
    docType = "markdown",
  ): Promise<UploadSummary> {
    const summary: UploadSummary = {
      okCount: 0,
      failedCount: 0,
      invalidNames: [],
      serverErrors: [],
    };
    if (!fileList?.length) {
      return summary;
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
    summary.invalidNames = files.filter((f) => !isSupported(f)).map((f) => f.name);

    const results = await Promise.allSettled(
      valid.map((file) => uploadKnowledgeFile(file, docType)),
    );
    for (const r of results) {
      if (r.status === "fulfilled") {
        summary.okCount += 1;
      } else {
        summary.serverErrors.push(
          r.reason instanceof Error ? r.reason.message : String(r.reason),
        );
      }
    }
    summary.failedCount = summary.invalidNames.length + summary.serverErrors.length;
    statusText.value =
      `已上传 ${summary.okCount} 个文件` +
      (summary.failedCount ? `，${summary.failedCount} 个失败` : "");
    await fetchKnowledgeFiles();
    return summary;
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
    clearSessionMessages(id);
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
    // 持久化当前停留的会话，刷新页面后能恢复「正在看的那一个」而非落到旧会话
    saveSessionIdToStorage(id);
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
          saveSessionMessages(id, history);
        }
      } catch (error) {
        // 后端不可用时保留本地消息
      }
    }
  }

  async function loadSessions() {
    const list = await getSessionList();
    sessions.value = list.map((s) => {
      // 优先用本地缓存的消息恢复界面，避免刷新丢失（特别是处理中被打断的请求）。
      const restored = loadSessionMessages(s.session_id);
      return createSession(s.title || "新会话", s.session_id, restored ?? undefined);
    });
  }

  async function initFromLocalStorage() {
    const savedSessionId = loadSessionIdFromStorage();
    try {
      await loadSessions();
      if (sessions.value.length) {
        if (savedSessionId && sessions.value.some((s) => s.id === savedSessionId)) {
          await switchSession(savedSessionId);
        } else {
          // 即使没有已存 id，也要对首个会话走 switchSession 拉历史，
          // 否则首个会话只有本地问候语、不回放后端消息。
          await switchSession(sessions.value[0].id);
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
    // 恢复被刷新打断的请求：当前会话最后一条是用户消息且尚无回复时，
    // 自动续发该消息以取回回复（不重复追加用户消息，避免刷新后出现重复）。
    const msgs = activeSession.value?.messages ?? [];
    const last = msgs[msgs.length - 1];
    if (last && last.role === "user" && !pending.value) {
      resumeInterruptedTurn(last.content);
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
      // 按后端回传的 session_id 定位目标聊天框渲染消息，避免「请求在途时切换会话」
      // 导致回复串到当前激活会话的问题；本地找不到该会话时回退到当前激活会话兜底。
      const target = sessions.value.find((s) => s.id === response.session_id) ?? activeSession.value;
      target.messages.push({
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: response.reply,
      });
      target.session = response.session_state;
      target.turns.unshift({
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
      touchTargetSession(target);
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
      saveSessionMessages(target.id, target.messages);
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

  // 刷新时若请求处理中被打断，最后一条用户消息尚无回复：复用已有用户消息，
  // 仅把内容重新发给后端取回回复，避免重复追加用户消息。
  async function resumeInterruptedTurn(content: string) {
    if (!content.trim() || pending.value) return;
    pending.value = true;
    statusText.value = "正在恢复上一次未完成的请求…";
    requestStart.value = Date.now();
    resetLiveTurn();

    try {
      await client.send({
        session_id: sessionId.value,
        channel: channel.value.trim() || "web",
        message: content,
      });
    } catch (error) {
      pending.value = false;
      backendReady.value = false;
      liveTrace.value.push("SSE 连接失败，回退到 HTTP /chat");
      try {
        const response = await postChat({
          session_id: sessionId.value,
          channel: channel.value.trim() || "web",
          message: content,
        });
        handleSocketEvent({ type: "final", response });
      } catch (fallbackError) {
        appendMessage({
          id: `error-${Date.now()}`,
          role: "assistant",
          content: "请求恢复失败，请重新发送该消息。",
        });
        statusText.value = "恢复失败";
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
    resumeInterruptedTurn,
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
