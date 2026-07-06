<script setup lang="ts">
import type { HandoffToolData } from "@/types/chat";

defineProps<{
  handoff: HandoffToolData;
}>();
</script>

<template>
  <article class="detail-card">
    <div class="detail-head">
      <div>
        <p class="panel-label">人工服务单</p>
        <h3>{{ handoff.ticket_id }}</h3>
      </div>
      <span class="status-badge handoff">handoff</span>
    </div>
    <p class="handoff-summary">{{ handoff.summary }}</p>
  </article>
</template>
