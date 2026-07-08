<script setup lang="ts">
import { computed } from "vue";
import { useChatStore } from "@/stores/chat";

const store = useChatStore();

const liveStats = computed(() => {
  return {
    mainIntent: store.sessionSnapshot.mainIntent,
    subIntent: store.sessionSnapshot.subIntent,
    stage: store.sessionSnapshot.stage,
    needsClarification: store.sessionSnapshot.clarify === 'yes',
    missingSlotsCount: store.sessionSnapshot.missingSlots.length,
    liveIntent: store.liveIntent,
    liveStage: store.liveStage,
    pending: store.pending,
    messageCount: store.activeSession?.messages?.length || 0,
  };
});
</script>

<template>
  <div class="live-stats-bar">
    <div class="stats-row">
      <!-- 连接状态指示灯 -->
      <div class="stat-indicator" :class="{ connected: store.backendReady, disconnected: !store.backendReady }">
        <span class="indicator-dot"></span>
        <span class="indicator-text">{{ store.backendReady ? '后端已连接' : '后端未连接' }}</span>
      </div>

      <!-- 处理状态 -->
      <div class="stat-item" v-if="liveStats.pending">
        <span class="stat-icon">⏳</span>
        <span class="stat-text">处理中...</span>
      </div>

      <!-- 意图识别结果 -->
      <div class="stat-item" v-if="liveStats.mainIntent && liveStats.mainIntent !== '-'">
        <span class="stat-label">意图:</span>
        <span class="stat-value">{{ liveStats.mainIntent }}</span>
        <span class="stat-arrow">/</span>
        <span class="stat-value">{{ liveStats.subIntent }}</span>
      </div>

      <!-- 阶段 -->
      <div class="stat-item" v-if="liveStats.stage && liveStats.stage !== '-'">
        <span class="stat-label">阶段:</span>
        <span class="stat-value stage">{{ liveStats.stage }}</span>
      </div>

      <!-- 缺失槽位提醒 -->
      <div class="stat-item warning" v-if="liveStats.missingSlotsCount > 0">
        <span class="stat-icon">⚠️</span>
        <span class="stat-text">缺失 {{ liveStats.missingSlotsCount }} 个槽位</span>
      </div>

      <!-- 消息计数 -->
      <div class="stat-item count">
        <span class="stat-label">消息:</span>
        <span class="stat-value">{{ liveStats.messageCount }}</span>
      </div>
    </div>

    <!-- 实时追踪信息 -->
    <div class="trace-preview" v-if="store.liveTrace.length > 0">
      <div class="trace-scroll">
        <span
          v-for="(trace, index) in store.liveTrace.slice(-3)"
          :key="index"
          class="trace-item"
        >
          {{ trace }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.live-stats-bar {
  background: var(--main-bg);
  border-top: 1px solid var(--line);
  padding: 8px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}

.stats-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 0.8rem;
}

.stat-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 500;
}

.stat-indicator.connected {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

.stat-indicator.disconnected {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.indicator-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--ink);
}

.stat-item.warning {
  color: #f59e0b;
  font-weight: 500;
}

.stat-icon {
  font-size: 0.9rem;
}

.stat-label {
  color: var(--ink-soft);
  font-weight: 500;
}

.stat-value {
  font-weight: 600;
  color: var(--ink);
}

.stat-value.stage {
  color: #8b5cf6;
}

.stat-arrow {
  color: var(--ink-soft);
  margin: 0 2px;
}

.stat-item.count {
  margin-left: auto;
  color: var(--ink-soft);
}

.trace-preview {
  background: var(--bg);
  border-radius: 6px;
  padding: 6px 10px;
  max-height: 60px;
  overflow: hidden;
}

.trace-scroll {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.trace-item {
  font-size: 0.7rem;
  color: var(--ink-soft);
  font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 768px) {
  .stats-row {
    gap: 8px;
  }

  .stat-item {
    font-size: 0.75rem;
  }
}
</style>
