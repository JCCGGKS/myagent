<script setup lang="ts">
import { computed } from "vue";

import type { OrderToolData } from "@/types/chat";

const props = defineProps<{
  order: OrderToolData;
}>();

const statusClass = computed(() => props.order.status.toLowerCase().replace(/\s+/g, "-"));
</script>

<template>
  <article class="detail-card">
    <div class="detail-head">
      <div>
        <p class="panel-label">订单详情</p>
        <h3>{{ order.order_id }}</h3>
      </div>
      <span class="status-badge" :class="statusClass">{{ order.status }}</span>
    </div>
    <dl class="detail-grid">
      <div>
        <dt>商品</dt>
        <dd>{{ order.product_name }}</dd>
      </div>
      <div>
        <dt>金额</dt>
        <dd>¥ {{ order.amount }}</dd>
      </div>
    </dl>
  </article>
</template>
