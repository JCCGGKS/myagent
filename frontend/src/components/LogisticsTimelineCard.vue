<script setup lang="ts">
import type { LogisticsToolData } from "@/types/chat";

defineProps<{
  logistics: LogisticsToolData;
}>();
</script>

<template>
  <article class="detail-card">
    <div class="detail-head">
      <div>
        <p class="panel-label">物流详情</p>
        <h3>{{ logistics.order_id }}</h3>
      </div>
      <span class="status-badge logistics">{{ logistics.tracking_status }}</span>
    </div>
    <ol class="timeline">
      <li
        v-for="(event, index) in logistics.timeline"
        :key="`${event.time}-${index}`"
        class="timeline-item"
        :class="{ latest: index === logistics.timeline.length - 1 }"
      >
        <span class="timeline-dot"></span>
        <div>
          <p class="timeline-time">{{ event.time }}</p>
          <p class="timeline-status">{{ event.status }}</p>
        </div>
      </li>
    </ol>
  </article>
</template>
