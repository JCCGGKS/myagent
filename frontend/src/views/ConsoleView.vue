<script setup lang="ts">
import { onMounted, ref } from "vue";

import TurnTracePanel from "@/components/TurnTracePanel.vue";
import { useChatStore } from "@/stores/chat";

const store = useChatStore();
const fileInput = ref<HTMLInputElement | null>(null);

const prompts = [
  "退款多久到账？",
  "帮我查一下订单 A1001",
  "物流到哪了？订单号 A1002",
  "转人工",
];

// Sidebar menu state
const expandedMenu = ref<string | null>('chat'); // 'chat' or 'knowledge'
const activeSessionMenu = ref<string | null>(null);

function toggleMenu(menu: string) {
  if (expandedMenu.value === menu) {
    expandedMenu.value = null;
  } else {
    expandedMenu.value = menu;
    store.activePanel = menu as 'chat' | 'knowledge';
  }
}

function toggleSessionMenu(sessionId: string) {
  if (activeSessionMenu.value === sessionId) {
    activeSessionMenu.value = null;
  } else {
    activeSessionMenu.value = sessionId;
  }
}

function renameSession(sessionId: string) {
  // TODO: Implement rename functionality
  console.log('Rename session:', sessionId);
  alert('重命名功能开发中...');
}

function deleteSession(sessionId: string) {
  if (confirm('确定要删除这个会话吗？')) {
    store.removeSession(sessionId);
  }
}

function pinSession(sessionId: string) {
  // TODO: Implement pin functionality
  console.log('Pin session:', sessionId);
  alert('置顶功能开发中...');
}

function triggerUpload() {
  fileInput.value?.click();
}

function onFileChange(event: Event) {
  const target = event.target as HTMLInputElement;
  store.uploadKnowledgeFiles(target.files);
  target.value = "";
}

function handleEnter() {
  if (store.draft.trim() && !store.pending) {
    store.sendMessage();
  }
}

function handleShiftEnter() {
  store.draft += '\n';
}

onMounted(async () => {
  await store.refreshHealth();
  await store.connectSocket();
});
</script>

<template>
  <div class="app-shell">
    <!-- Left Sidebar -->
    <aside class="session-sidebar">
      <div class="sidebar-brand">
        <h1>客服助手</h1>
      </div>

      <!-- Menu Items -->
      <nav class="sidebar-nav">
        <!-- Chat Menu -->
        <div class="menu-item">
          <button
            type="button"
            class="menu-header"
            :class="{ active: expandedMenu === 'chat' }"
            @click="toggleMenu('chat')"
          >
            <span class="menu-icon">💬</span>
            <span class="menu-title">会话管理</span>
            <span class="menu-arrow">{{ expandedMenu === 'chat' ? '▼' : '▶' }}</span>
          </button>

          <div v-if="expandedMenu === 'chat'" class="menu-content">
            <div
              v-for="session in store.sessions"
              :key="session.id"
              class="session-item-flat"
              :class="{ active: session.id === store.activeSessionId }"
            >
                <div class="session-item-content" @click="store.switchSession(session.id)">
                  <div class="session-item-title">{{ session.title }}</div>
                </div>
              <button
                type="button"
                class="session-menu-trigger"
                @click.stop="toggleSessionMenu(session.id)"
              >
                ⋯
              </button>

              <!-- Session Menu -->
              <div
                v-if="activeSessionMenu === session.id"
                class="session-menu"
              >
                <button
                  type="button"
                  class="session-menu-item"
                  @click.stop="renameSession(session.id); activeSessionMenu = null;"
                >
                  ✏️ 重命名
                </button>
                <button
                  type="button"
                  class="session-menu-item"
                  @click.stop="deleteSession(session.id); activeSessionMenu = null;"
                >
                  🗑️ 删除
                </button>
                <button
                  type="button"
                  class="session-menu-item"
                  @click.stop="pinSession(session.id); activeSessionMenu = null;"
                >
                  📌 置顶
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Knowledge Menu -->
        <div class="menu-item">
          <button
            type="button"
            class="menu-header"
            :class="{ active: expandedMenu === 'knowledge' }"
            @click="toggleMenu('knowledge')"
          >
            <span class="menu-icon">📚</span>
            <span class="menu-title">知识库</span>
            <span class="menu-arrow">{{ expandedMenu === 'knowledge' ? '▼' : '▶' }}</span>
          </button>

          <div v-if="expandedMenu === 'knowledge'" class="menu-content">
            <div class="file-list">
              <div
                v-for="file in store.knowledgeFiles"
                :key="file.id"
                class="file-item"
              >
                <div class="file-name">{{ file.name }}</div>
                <div class="file-meta">{{ file.sizeLabel }} • {{ file.status }}</div>
              </div>

              <div v-if="store.knowledgeFiles.length === 0" class="empty-hint">
                暂无文件
              </div>
            </div>
          </div>
        </div>
      </nav>
    </aside>

    <!-- Main Workspace -->
    <main class="workspace">
      <!-- Chat Panel -->
      <template v-if="store.activePanel === 'chat'">
        <div class="chat-shell">
          <div class="chat-header">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <h2>{{ store.activeSession?.title || '新会话' }}</h2>
              <button
                type="button"
                class="new-session-button"
                @click="store.createNewSession"
                style="
                  padding: 8px 16px;
                  font-size: 0.9rem;
                "
              >
                + 新建会话
              </button>
            </div>
          </div>

          <div class="message-list">
            <div
              v-for="message in store.messages"
              :key="message.id"
              class="message-card"
              :class="message.role"
            >
              <div class="message-content">{{ message.content }}</div>
            </div>
          </div>

          <div class="prompt-row">
            <button
              v-for="prompt in prompts"
              :key="prompt"
              type="button"
              class="soft-button"
              @click="store.sendMessage(prompt)"
            >
              {{ prompt }}
            </button>
          </div>

          <div class="composer">
            <textarea
              v-model="store.draft"
              placeholder="输入消息，按回车发送，Shift+回车换行"
              :disabled="store.pending"
              @keydown.enter.exact.prevent="handleEnter"
              @keydown.shift.enter.prevent="handleShiftEnter"
            />
            <div class="composer-foot">
              <span class="status-text">{{ store.statusText }}</span>
              <button
                type="button"
                class="submit-button"
                :disabled="store.pending || !store.draft.trim()"
                @click="store.sendMessage()"
              >
                {{ store.pending ? '发送中...' : '发送' }}
              </button>
            </div>
          </div>
        </div>
      </template>

      <!-- Knowledge Panel -->
      <template v-else>
        <div class="chat-shell">
          <div class="chat-header">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <div>
                <h2>知识库管理</h2>
                <p class="header-hint">上传和管理知识库文件</p>
              </div>
              <button
                type="button"
                class="upload-button"
                @click="triggerUpload"
                style="
                  padding: 8px 16px;
                  font-size: 0.9rem;
                "
              >
                📤 上传文件
              </button>
              <input
                ref="fileInput"
                type="file"
                multiple
                style="display: none;"
                @change="onFileChange"
              />
            </div>
          </div>

          <div class="message-list">
            <div
              v-for="file in store.knowledgeFiles"
              :key="file.id"
              class="message-card assistant"
              style="max-width: 100%; margin-bottom: 12px;"
            >
              <p><strong>{{ file.name }}</strong></p>
              <p style="font-size: 0.85rem; color: var(--ink-soft); margin-top: 6px;">
                {{ file.sizeLabel }} • {{ file.uploadedAt }} • {{ file.status }}
              </p>
            </div>

            <div v-if="store.knowledgeFiles.length === 0" style="text-align: center; padding: 60px 20px; color: var(--ink-soft);">
              <p style="font-size: 3rem; margin-bottom: 16px;">📚</p>
              <p style="font-size: 1.1rem; margin-bottom: 8px;">暂无文件</p>
              <p style="font-size: 0.9rem;">点击右上角"上传文件"按钮添加</p>
            </div>
          </div>
        </div>
      </template>
    </main>
  </div>
</template>
