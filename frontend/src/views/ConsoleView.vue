<script setup lang="ts">
import { onMounted } from "vue";

import TurnTracePanel from "@/components/TurnTracePanel.vue";
import { useChatStore } from "@/stores/chat";

const store = useChatStore();

const prompts = [
  "退款多久到账？",
  "帮我查一下订单 A1001",
  "物流到哪了？订单号 A1002",
  "转人工",
];

onMounted(async () => {
  await store.refreshHealth();
  await store.connectSocket();
});
</script>

<template>
  <main class="app-shell">
    <aside class="session-sidebar">
      <div class="sidebar-head">
        <div>
          <p class="eyebrow">Conversation</p>
          <h1>会话</h1>
        </div>
        <button type="button" class="new-session-button" @click="store.createNewSession">
          新建会话
        </button>
      </div>

      <div class="session-toolbar">
        <div class="backend-state compact" :class="{ offline: store.backendReady === false }">
          <span class="status-dot"></span>
          <p v-if="store.socketConnected">已连接</p>
          <p v-else-if="store.backendReady === true">仅 API 可用</p>
          <p v-else-if="store.backendReady === false">后端离线</p>
          <p v-else>探测中</p>
        </div>
      </div>

      <label class="session-search">
        <span>搜索会话</span>
        <input v-model="store.sessionSearch" type="text" placeholder="搜索标题或内容" />
      </label>

      <section class="session-list">
        <div v-for="group in store.groupedSessions" :key="group.label" class="session-group">
          <p class="session-group-label">{{ group.label }}</p>
          <div
            v-for="session in group.items"
            :key="session.id"
            class="session-item"
            :class="{ active: session.id === store.activeSessionId }"
          >
            <div class="session-item-head">
              <button type="button" class="session-main" @click="store.switchSession(session.id)">
                <template v-if="store.renamingSessionId === session.id">
                  <input
                    v-model="store.renameDraft"
                    class="session-rename-input"
                    type="text"
                    maxlength="20"
                    @click.stop
                    @keyup.enter="store.submitRenameSession(session.id)"
                    @keyup.esc="store.cancelRenameSession()"
                  />
                </template>
                <template v-else>
                  <h2>{{ session.title }}</h2>
                </template>
              </button>
              <span>{{ session.updatedAt }}</span>
            </div>
            <p @click="store.switchSession(session.id)">{{ session.preview }}</p>
            <div class="session-item-actions">
              <button
                v-if="store.renamingSessionId === session.id"
                type="button"
                class="session-action"
                @click="store.submitRenameSession(session.id)"
              >
                保存
              </button>
              <button
                v-else
                type="button"
                class="session-action"
                @click="store.startRenameSession(session.id)"
              >
                重命名
              </button>
              <button
                v-if="store.renamingSessionId === session.id"
                type="button"
                class="session-action ghost"
                @click="store.cancelRenameSession()"
              >
                取消
              </button>
              <button
                v-else
                type="button"
                class="session-action ghost"
                @click="store.removeSession(session.id)"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      </section>
    </aside>

    <section class="workspace">
      <section class="console-panel">
        <header class="console-head">
          <div class="chat-title">
            <p class="eyebrow">Current Chat</p>
            <h2>{{ store.activeSession.title }}</h2>
            <p class="chat-subtitle">
              {{ store.sessionSnapshot.mainIntent }} / {{ store.sessionSnapshot.subIntent }} /
              {{ store.sessionSnapshot.stage }} / {{ store.sessionSnapshot.clarify }}
            </p>
          </div>
          <div class="identity-grid">
            <label>
              <span>用户 ID</span>
              <input v-model="store.userId" type="text" />
            </label>
            <label>
              <span>渠道</span>
              <input v-model="store.channel" type="text" />
            </label>
          </div>
        </header>

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

        <section class="message-list" aria-live="polite">
          <article
            v-for="message in store.messages"
            :key="message.id"
            class="message-card"
            :class="[message.role, { meta: message.tone === 'meta' }]"
          >
            <p class="message-role">{{ message.role }}</p>
            <p>{{ message.content }}</p>
          </article>
        </section>

        <form class="composer" @submit.prevent="store.sendMessage()">
          <label class="composer-label" for="message-input">消息</label>
          <textarea
            id="message-input"
            v-model="store.draft"
            rows="4"
            placeholder="例如：帮我查一下订单 A1001"
            :disabled="store.pending"
          />
          <div class="composer-foot">
            <p>{{ store.statusText }}</p>
            <button type="submit" class="submit-button" :disabled="store.pending">
              {{ store.pending ? "发送中..." : "发送消息" }}
            </button>
          </div>
        </form>
      </section>

      <section class="overview-panel compact">
        <div class="overview-grid">
          <article class="overview-card">
            <p class="panel-label">Session ID</p>
            <pre>{{ store.sessionId }}</pre>
          </article>
          <article class="overview-card">
            <p class="panel-label">Slots</p>
            <pre>{{ JSON.stringify(store.sessionSnapshot.slots, null, 2) }}</pre>
          </article>
          <article class="overview-card">
            <p class="panel-label">Missing</p>
            <pre>{{ JSON.stringify(store.sessionSnapshot.missingSlots, null, 2) }}</pre>
          </article>
          <article class="overview-card">
            <p class="panel-label">Summary</p>
            <pre>{{ store.sessionSnapshot.summary }}</pre>
          </article>
        </div>
      </section>

      <TurnTracePanel :turns="store.turns" />
    </section>
  </main>
</template>
