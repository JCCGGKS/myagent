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

function toggleMenu(menu: string) {
  if (expandedMenu.value === menu) {
    expandedMenu.value = null;
  } else {
    expandedMenu.value = menu;
    store.activePanel = menu as 'chat' | 'knowledge';
  }
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
            <button
              type="button"
              class="new-session-button"
              @click="store.createNewSession"
            >
              + 新建会话
            </button>

            <div class="session-list">
              <div
                v-for="session in store.sessions"
                :key="session.id"
                class="session-item"
                :class="{ active: session.id === store.activeSessionId }"
                @click="store.switchSession(session.id)"
              >
                <div class="session-item-title">{{ session.title }}</div>
                <div class="session-item-preview">{{ session.preview }}</div>
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
            <button type="button" class="upload-button" @click="triggerUpload">
              上传文件
            </button>
            <input
              ref="fileInput"
              type="file"
              multiple
              style="display: none;"
              @change="onFileChange"
            />

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
                暂无文件，点击上方按钮上传
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
            <h2>{{ store.activeSession?.title || '新会话' }}</h2>
          </div>

          <div class="message-list">
            <div
              v-for="message in store.messages"
              :key="message.id"
              class="message-card"
              :class="message.role"
            >
              <p>{{ message.content }}</p>
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
            <h2>知识库管理</h2>
            <p class="header-hint">在左侧边栏的"知识库"菜单中管理文件</p>
          </div>

          <div class="message-list" style="display: flex; align-items: center; justify-content: center;">
            <div style="text-align: center; color: var(--ink-soft);">
              <p style="font-size: 1.2rem; margin-bottom: 12px;">📚</p>
              <p>请在左侧边栏的"知识库"菜单中</p>
              <p>上传和管理知识库文件</p>
            </div>
          </div>
        </div>
      </template>
    </main>
  </div>
</template>
