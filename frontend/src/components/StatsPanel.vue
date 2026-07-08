<script setup lang="ts">
import { computed } from "vue";
import { useChatStore } from "@/stores/chat";

const store = useChatStore();

const stats = computed(() => {
  const snapshot = store.sessionSnapshot;
  
  return {
    // 会话基本信息
    sessionId: store.activeSessionId?.slice(0, 16) + '...' || '-',
    messageCount: store.activeSession?.messages?.length || 0,
    turnCount: store.turns?.length || 0,
    
    // 意图识别信息
    mainIntent: snapshot.mainIntent,
    subIntent: snapshot.subIntent,
    stage: snapshot.stage,
    
    // 槽位信息
    slots: snapshot.slots,
    missingSlots: snapshot.missingSlots,
    needsClarification: snapshot.clarify === 'yes',
    
    // 实时信息
    liveIntent: store.liveIntent,
    liveStage: store.liveStage,
    hasToolResult: !!store.liveToolResult,
  };
});

function formatSlots(slots: Record<string, any>) {
  if (!slots || Object.keys(slots).length === 0) return '无';
  return Object.entries(slots)
    .map(([key, value]) => `${key}: ${value || '空'}`)
    .join(', ');
}
</script>

<template>
  <section class="stats-panel">
    <div class="stats-head">
      <p class="eyebrow">Statistics</p>
      <h2>统计信息</h2>
    </div>

    <div class="stats-content">
      <!-- 会话信息 -->
      <div class="stats-section">
        <h3 class="section-title">会话信息</h3>
        <div class="stat-item">
          <span class="stat-label">会话ID</span>
          <span class="stat-value mono">{{ stats.sessionId }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">消息数</span>
          <span class="stat-value">{{ stats.messageCount }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">轮次数</span>
          <span class="stat-value">{{ stats.turnCount }}</span>
        </div>
      </div>

      <!-- 意图识别 -->
      <div class="stats-section">
        <h3 class="section-title">意图识别</h3>
        <div class="stat-item">
          <span class="stat-label">主意图</span>
          <span class="stat-value intent-value">{{ stats.mainIntent }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">子意图</span>
          <span class="stat-value intent-value">{{ stats.subIntent }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">阶段</span>
          <span class="stat-value stage-value">{{ stats.stage }}</span>
        </div>
        <div class="stat-item" v-if="stats.needsClarification">
          <span class="stat-label">需要澄清</span>
          <span class="stat-value status-pending">是</span>
        </div>
      </div>

      <!-- 槽位信息 -->
      <div class="stats-section" v-if="stats.missingSlots.length > 0 || Object.keys(stats.slots).length > 0">
        <h3 class="section-title">槽位信息</h3>
        <div class="stat-item" v-if="stats.missingSlots.length > 0">
          <span class="stat-label">缺失槽位</span>
          <span class="stat-value missing-slots">{{ stats.missingSlots.join(', ') }}</span>
        </div>
        <div class="stat-item" v-if="Object.keys(stats.slots).length > 0">
          <span class="stat-label">已填槽位</span>
          <span class="stat-value slots-value">{{ formatSlots(stats.slots) }}</span>
        </div>
      </div>

      <!-- 实时信息 -->
      <div class="stats-section" v-if="stats.liveIntent || stats.liveStage || stats.hasToolResult">
        <h3 class="section-title">实时信息</h3>
        <div class="stat-item" v-if="stats.liveIntent">
          <span class="stat-label">识别意图</span>
          <span class="stat-value live-value">{{ stats.liveIntent }}</span>
        </div>
        <div class="stat-item" v-if="stats.liveStage">
          <span class="stat-label">当前阶段</span>
          <span class="stat-value live-value">{{ stats.liveStage }}</span>
        </div>
        <div class="stat-item" v-if="stats.hasToolResult">
          <span class="stat-label">工具结果</span>
          <span class="stat-value status-ok">已返回</span>
        </div>
      </div>

      <!-- 空状态 -->
      <div class="stats-empty" v-if="stats.turnCount === 0 && !stats.pending">
        <p>发送消息后显示统计信息</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.stats-panel {
  background: white;
  border-radius: 12px;
  border: 1px solid var(--line);
  overflow: hidden;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.stats-head {
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--bg);
}

.eyebrow {
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-soft);
  margin: 0 0 2px;
}

.stats-head h2 {
  font-size: 1rem;
  font-weight: 700;
  margin: 0;
  color: var(--ink);
}

.stats-content {
  padding: 12px;
  overflow-y: auto;
  flex: 1;
}

.stats-section {
  margin-bottom: 16px;
}

.stats-section:last-child {
  margin-bottom: 0;
}

.section-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--ink-soft);
  margin: 0 0 8px 0;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border-muted);
}

.stat-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 6px 0;
  font-size: 0.85rem;
  line-height: 1.4;
}

.stat-label {
  color: var(--ink-soft);
  font-weight: 500;
  flex-shrink: 0;
  margin-right: 8px;
}

.stat-value {
  color: var(--ink);
  font-weight: 600;
  text-align: right;
  word-break: break-word;
}

.stat-value.mono {
  font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', monospace;
  font-size: 0.8rem;
}

.status-ok {
  color: #10b981;
}

.status-error {
  color: #ef4444;
}

.status-pending {
  color: #f59e0b;
}

.status-idle {
  color: var(--ink-soft);
}

.intent-value {
  color: #6366f1;
}

.stage-value {
  color: #8b5cf6;
}

.missing-slots {
  color: #ef4444;
  font-size: 0.8rem;
}

.slots-value {
  color: #10b981;
  font-size: 0.8rem;
}

.live-value {
  color: #3b82f6;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.6;
  }
}

.stats-empty {
  text-align: center;
  padding: 24px 16px;
  color: var(--ink-soft);
  font-size: 0.85rem;
}

.stats-empty p {
  margin: 0;
}
</style>
