<script setup lang="ts">
import HandoffCard from "@/components/HandoffCard.vue";
import LogisticsTimelineCard from "@/components/LogisticsTimelineCard.vue";
import OrderDetailCard from "@/components/OrderDetailCard.vue";
import type {
  HandoffToolData,
  LogisticsToolData,
  OrderToolData,
  ToolResult,
  TurnItem,
} from "@/types/chat";

defineProps<{
  turns: TurnItem[];
}>();

function getOrderData(result: ToolResult | null): OrderToolData | null {
  return result?.kind === "order" && result.sanitized_result
    ? (result.sanitized_result as OrderToolData)
    : null;
}

function getLogisticsData(result: ToolResult | null): LogisticsToolData | null {
  return result?.kind === "logistics" && result.sanitized_result
    ? (result.sanitized_result as LogisticsToolData)
    : null;
}

function getHandoffData(result: ToolResult | null): HandoffToolData | null {
  return result?.kind === "handoff" && result.sanitized_result
    ? (result.sanitized_result as HandoffToolData)
    : null;
}
</script>

<template>
  <section class="trace-panel">
    <div class="trace-head">
      <div>
        <p class="eyebrow">Turn Trace</p>
        <h2>轮次历史</h2>
      </div>
    </div>

    <div class="turn-list" v-if="turns.length">
      <article v-for="turn in turns" :key="turn.id" class="turn-card">
        <div class="turn-meta">
          <span>{{ turn.createdAt }}</span>
          <span>{{ turn.mainIntent }}</span>
          <span>{{ turn.subIntent }}</span>
          <span>{{ turn.stage }}</span>
        </div>
        <p class="turn-summary">{{ turn.summary || "本轮未生成摘要" }}</p>
        <ul class="trace-list">
          <li v-for="item in turn.trace" :key="item">{{ item }}</li>
        </ul>

        <OrderDetailCard v-if="getOrderData(turn.toolResult)" :order="getOrderData(turn.toolResult)!" />
        <LogisticsTimelineCard
          v-else-if="getLogisticsData(turn.toolResult)"
          :logistics="getLogisticsData(turn.toolResult)!"
        />
        <HandoffCard v-else-if="getHandoffData(turn.toolResult)" :handoff="getHandoffData(turn.toolResult)!" />
      </article>
    </div>

    <div v-else class="trace-empty">
      <p>还没有轮次记录。发送消息后，这里会显示本轮路由和工具调用详情。</p>
    </div>
  </section>
</template>
