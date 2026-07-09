<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import StatsPanel from "@/components/StatsPanel.vue";
import TurnTracePanel from "@/components/TurnTracePanel.vue";
import KnowledgeBuildPanel from "@/views/KnowledgeBuildPanel.vue";
import { useChatStore } from "@/stores/chat";
import { useAuthStore } from "@/stores/auth";

const store = useChatStore();
const auth = useAuthStore();
const router = useRouter();
const fileInput = ref<HTMLInputElement | null>(null);

function handleLogout() {
  auth.logout();
  router.push("/login");
}

const prompts = [
  "退款多久到账？",
  "帮我查一下订单 A1001",
  "物流到哪了？订单号 A1002",
  "转人工",
];

// Sidebar menu state
const expandedMenu = ref<string | null>('chat'); // 'chat' or 'knowledge'
const activeSessionMenu = ref<string | null>(null);
const showStatsPanel = ref(true); // Control stats panel visibility

// Retrieval strategy
const strategies = ['向量检索', '关键词检索', '混合检索'];
const currentStrategy = ref('混合检索');
const maxRecall = ref(5);
const minScore = ref(0.5);
const showConfigPanel = ref(false);

// Temporary config values
const tempStrategy = ref(currentStrategy.value);
const tempMaxRecall = ref(maxRecall.value);
const tempMinScore = ref(minScore.value);

function openConfigPanel() {
  // Copy current values to temp
  tempStrategy.value = currentStrategy.value;
  tempMaxRecall.value = maxRecall.value;
  tempMinScore.value = minScore.value;
  showConfigPanel.value = true;
}

function confirmConfig() {
  // Apply temp values to actual config
  currentStrategy.value = tempStrategy.value;
  maxRecall.value = tempMaxRecall.value;
  minScore.value = tempMinScore.value;
  showConfigPanel.value = false;
}

function cancelConfig() {
  showConfigPanel.value = false;
}

function toggleMenu(menu: string) {
  if (expandedMenu.value === menu) {
    expandedMenu.value = null;
  } else {
    expandedMenu.value = menu;
    store.activePanel = menu as 'chat' | 'knowledge';
  }
}

function openKnowledge() {
  expandedMenu.value = 'knowledge';
  store.activePanel = 'knowledge';
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

function toggleStatsPanel() {
  showStatsPanel.value = !showStatsPanel.value;
}

onMounted(async () => {
  await store.refreshHealth();
  await store.initFromLocalStorage();
  await store.connectSocket();
  await auth.fetchMe();
});
</script>

<template>
  <div class="app-shell">
    <!-- Left Sidebar -->
    <aside class="session-sidebar">
      <div class="sidebar-brand">
        <h1>客服助手</h1>
      </div>

      <!-- Stats Panel Toggle -->
      <div class="sidebar-stats-toggle">
        <button
          type="button"
          class="menu-header"
          :class="{ active: showStatsPanel }"
          @click="toggleStatsPanel"
        >
          <span class="menu-icon">📊</span>
          <span class="menu-title">统计面板</span>
          <span class="menu-arrow">{{ showStatsPanel ? '▼' : '▶' }}</span>
        </button>
      </div>

      <!-- Stats Panel -->
      <div v-if="showStatsPanel" class="sidebar-stats">
        <StatsPanel />
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

        <!-- Knowledge Menu (一级栏目) -->
        <div class="menu-item">
          <button
            type="button"
            class="menu-header"
            :class="{ active: expandedMenu === 'knowledge' || store.activePanel === 'knowledge' }"
            @click="openKnowledge"
          >
            <span class="menu-icon">📚</span>
            <span class="menu-title">知识库</span>
            <span class="menu-arrow">{{ expandedMenu === 'knowledge' ? '▼' : '▶' }}</span>
          </button>

          <!-- 二级栏目 -->
          <div v-if="expandedMenu === 'knowledge'" class="menu-content">
            <button
              type="button"
              class="submenu-item"
              :class="{ active: store.activePanel === 'knowledge' }"
              @click="store.activePanel = 'knowledge'"
            >
              <span class="submenu-title">知识库构建</span>
            </button>
          </div>
        </div>
      </nav>

      <!-- 用户与登出 -->
      <div class="sidebar-user">
        <div class="sidebar-user-info">
          <span class="sidebar-user-name">{{ auth.user?.username || '未登录' }}</span>
          <span class="sidebar-user-email">{{ auth.user?.email || '' }}</span>
        </div>
        <button type="button" class="sidebar-logout" @click="handleLogout">
          退出登录
        </button>
      </div>
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
        <KnowledgeBuildPanel />
      </template>
    </main>
  </div>
</template>
