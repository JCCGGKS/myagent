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
  <main class="shell">
    <section class="hero-panel">
      <div class="hero-copy">
        <p class="eyebrow">Customer Service Agent MVP</p>
        <h1>客服 Agent 控制台</h1>
        <p class="intro">
          一个用于展示 FAQ、订单查询、物流查询、转人工 的实时控制台。左侧看能力与会话轨迹，右侧直接发起对话并观察路由结果。
        </p>
      </div>

      <div class="capability-grid">
        <article class="capability-card">
          <span>01</span>
          <h2>FAQ</h2>
          <p>命中知识库后直接回复，适合售后规则、退款时效、发票说明等问题。</p>
        </article>
        <article class="capability-card">
          <span>02</span>
          <h2>订单查询</h2>
          <p>自动抽取订单号，缺槽位时主动追问，补齐后返回当前订单状态。</p>
        </article>
        <article class="capability-card">
          <span>03</span>
          <h2>物流查询</h2>
          <p>复用订单号槽位查询物流，适合连续对话中的上下文承接。</p>
        </article>
        <article class="capability-card">
          <span>04</span>
          <h2>转人工</h2>
          <p>生成服务单号并保留摘要，方便人工客服接手后继续处理。</p>
        </article>
      </div>

      <section class="inspector-panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Session Inspector</p>
            <h2>会话状态</h2>
          </div>
          <button type="button" class="soft-button" @click="store.refreshSession">
            刷新状态
          </button>
        </div>

        <dl class="session-grid">
          <div>
            <dt>Session ID</dt>
            <dd>{{ store.sessionId }}</dd>
          </div>
          <div>
            <dt>Intent</dt>
            <dd>{{ store.sessionSnapshot.intent }}</dd>
          </div>
          <div>
            <dt>Stage</dt>
            <dd>{{ store.sessionSnapshot.stage }}</dd>
          </div>
          <div>
            <dt>Clarify</dt>
            <dd>{{ store.sessionSnapshot.clarify }}</dd>
          </div>
        </dl>

        <div class="slots-grid">
          <article class="slot-card">
            <p class="panel-label">Slots</p>
            <pre>{{ JSON.stringify(store.sessionSnapshot.slots, null, 2) }}</pre>
          </article>
          <article class="slot-card">
            <p class="panel-label">Missing Slots</p>
            <pre>{{ JSON.stringify(store.sessionSnapshot.missingSlots, null, 2) }}</pre>
          </article>
          <article class="slot-card slot-card-wide">
            <p class="panel-label">摘要</p>
            <pre>{{ store.sessionSnapshot.summary }}</pre>
          </article>
        </div>
      </section>
    </section>

    <section class="console-panel">
      <header class="console-head">
        <div>
          <p class="eyebrow">Live Console</p>
          <h2>对话演示</h2>
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

      <div class="backend-state" :class="{ offline: store.backendReady === false }">
        <span class="status-dot"></span>
        <p v-if="store.socketConnected">WebSocket 已连接</p>
        <p v-else-if="store.backendReady === true">后端 API 可用，WebSocket 尚未建立</p>
        <p v-else-if="store.backendReady === false">后端 API 未连接，请先启动 FastAPI</p>
        <p v-else>正在探测后端状态</p>
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

    <TurnTracePanel class="trace-shell" :turns="store.turns" />
  </main>
</template>
