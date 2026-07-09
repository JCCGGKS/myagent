<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";

import { useChatStore } from "@/stores/chat";
import { getRagConfig, updateRagConfig, type RagConfig } from "@/lib/api";
import type { KnowledgeFileItem } from "@/types/chat";

const store = useChatStore();
const fileInput = ref<HTMLInputElement | null>(null);
const dragOver = ref(false);
const docType = ref<"markdown" | "json">("markdown");
const showConfigModal = ref(false);

const isUploading = computed(() =>
  store.knowledgeFiles.some((file) => file.status === "uploading"),
);

const strategyOptions = [
  { value: "bm25", label: "稀疏向量检索 (BM25)" },
  { value: "semantic", label: "语义向量检索" },
  { value: "hybrid", label: "混合检索" },
] as const;

const strategyLabel = computed(() => {
  switch (ragForm.retrieval_strategy) {
    case "bm25":
      return "稀疏向量检索 (BM25)";
    case "semantic":
      return "语义向量检索";
    case "hybrid":
      return "混合检索";
    default:
      return String(ragForm.retrieval_strategy);
  }
});

// 当前检索策略下，哪些配置项是“激活”的（其余置灰）
const activeFields = computed<Set<string>>(() => {
  const s = ragForm.retrieval_strategy;
  const set = new Set<string>(["top_k"]); // 所有策略通用
  if (s === "bm25") {
    set.add("metric_bm25");
    set.add("bm25_threshold");
  }
  if (s === "semantic") {
    set.add("metric_semantic");
    set.add("semantic_threshold");
  }
  if (s === "hybrid") {
    set.add("metric_semantic"); // hybrid 也用语义度量
    set.add("fusion_method");
    set.add("hybrid_threshold");
    set.add("rerank");
    // 仅加权融合时才可选语义权重
    if (ragForm.hybrid.fusion_method === "weighted") {
      set.add("weighted_alpha");
    }
  }
  return set;
});

// 每项解释是否“激活”（用于置灰判断）
function isActive(key: string) {
  return activeFields.value.has(key);
}

const stats = computed(() => {
  const files = store.knowledgeFiles;
  return {
    total: files.length,
    success: files.filter((f) => f.status === "success").length,
    indexing: files.filter((f) => f.status === "indexing").length,
    error: files.filter((f) => f.status === "error").length,
  };
});

// ---- 检索配置 ----
const defaultConfig: RagConfig = {
  retrieval_strategy: "hybrid",
  top_k: 5,
  bm25: { min_score_threshold: 5.0 },
  semantic: { metric: "cosine", min_score_threshold: 0.7 },
  hybrid: { fusion_method: "rrf", weighted_alpha: 0.5, min_score_threshold: 0.5 },
  rerank: { enabled: false, model: "" },
};
const ragForm = reactive<RagConfig>(structuredClone(defaultConfig));
// 最近一次成功保存/加载的配置快照，用于“取消”
const savedSnapshot = ref<RagConfig>(structuredClone(defaultConfig));
const configSaving = ref(false);
const configError = ref("");

function cloneConfig(cfg: RagConfig): RagConfig {
  return JSON.parse(JSON.stringify(cfg));
}

async function loadRagConfig() {
  try {
    const cfg = await getRagConfig();
    Object.assign(ragForm, cfg);
    savedSnapshot.value = cloneConfig(cfg);
  } catch (error) {
    console.warn("加载检索配置失败", error);
  }
}

function applySnapshot(cfg: RagConfig) {
  const next = cloneConfig(cfg);
  ragForm.retrieval_strategy = next.retrieval_strategy;
  ragForm.top_k = next.top_k;
  ragForm.bm25 = next.bm25;
  ragForm.semantic = next.semantic;
  ragForm.hybrid = next.hybrid;
  ragForm.rerank = next.rerank;
}

function cancelRagConfig() {
  // 放弃本次修改，恢复为最近一次保存/加载的配置
  applySnapshot(savedSnapshot.value);
  configError.value = "";
  showConfigModal.value = false;
}

function resetRagConfig() {
  // 重置为后端当前的已保存配置（即快照），停留弹窗以便查看
  applySnapshot(savedSnapshot.value);
  configError.value = "";
}

async function saveRagConfig() {
  configSaving.value = true;
  configError.value = "";
  try {
    const saved = await updateRagConfig(cloneConfig(ragForm));
    applySnapshot(saved);
    savedSnapshot.value = cloneConfig(saved);
    showConfigModal.value = false;
  } catch (error) {
    configError.value = error instanceof Error ? error.message : String(error);
  } finally {
    configSaving.value = false;
  }
}

onMounted(loadRagConfig);

function triggerUpload() {
  fileInput.value?.click();
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  store.uploadKnowledgeFiles(input.files, docType.value);
  input.value = "";
}

function onDrop(event: DragEvent) {
  dragOver.value = false;
  if (event.dataTransfer?.files?.length) {
    store.uploadKnowledgeFiles(event.dataTransfer.files, docType.value);
  }
}

function statusLabel(item: KnowledgeFileItem): string {
  switch (item.status) {
    case "uploading":
      return "上传中";
    case "success":
      return item.chunkCount ? `已入库 ${item.chunkCount} 块` : "已入库";
    case "error":
      return "失败";
    case "indexing":
      return "索引中";
    default:
      return "待处理";
  }
}
</script>

<template>
  <div class="kb-view">
    <header class="kb-header">
      <h1>知识库构建</h1>
      <p class="kb-subtitle">上传 Markdown / JSON 文档，自动分块并写入向量库。</p>
    </header>

    <section class="kb-stats">
      <div class="kb-stat">
        <span class="kb-stat-value">{{ stats.total }}</span>
        <span class="kb-stat-label">总计</span>
      </div>
      <div class="kb-stat">
        <span class="kb-stat-value success">{{ stats.success }}</span>
        <span class="kb-stat-label">已入库</span>
      </div>
      <div class="kb-stat">
        <span class="kb-stat-value warning">{{ stats.indexing }}</span>
        <span class="kb-stat-label">索引中</span>
      </div>
      <div class="kb-stat">
        <span class="kb-stat-value danger">{{ stats.error }}</span>
        <span class="kb-stat-label">失败</span>
      </div>
    </section>

    <section
      class="kb-dropzone"
      :class="{ 'is-over': dragOver }"
      @click="triggerUpload"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop.prevent="onDrop"
    >
      <input
        ref="fileInput"
        type="file"
        accept=".md,.markdown,.json"
        multiple
        hidden
        @change="onFileChange"
      />
      <div class="kb-dropzone-icon">⬆</div>
      <p class="kb-dropzone-text">点击或拖拽文件到此处上传</p>
      <p class="kb-dropzone-hint">支持 .md / .markdown / .json</p>
    </section>

    <section class="kb-toolbar">
      <label class="kb-field">
        <span>文档类型</span>
        <select v-model="docType">
          <option value="markdown">Markdown</option>
          <option value="json">JSON</option>
        </select>
      </label>

      <button class="kb-strategy-trigger" type="button" @click="showConfigModal = true">
        <span class="kb-strategy-label">检索策略</span>
        <span class="kb-strategy-value">{{ strategyLabel }}</span>
        <span class="kb-strategy-caret">⚙</span>
      </button>
    </section>

    <!-- 检索配置弹窗 -->
    <div v-if="showConfigModal" class="kb-modal-mask" @click.self="showConfigModal = false">
      <div class="kb-modal">
        <div class="kb-modal-head">
          <h3>检索配置</h3>
          <button class="kb-modal-close" type="button" @click="showConfigModal = false">✕</button>
        </div>
        <p v-if="configError" class="kb-file-error">{{ configError }}</p>

        <!-- 检索策略选择器 -->
        <div class="kb-strategy-bar">
          <button
            v-for="opt in strategyOptions"
            :key="opt.value"
            type="button"
            class="kb-strategy-tab"
            :class="{ 'is-active': ragForm.retrieval_strategy === opt.value }"
            @click="ragForm.retrieval_strategy = opt.value"
          >
            {{ opt.label }}
          </button>
        </div>

        <!-- 配置卡片组：随检索策略变化，不可选的项置灰 -->
        <div class="kb-config-cards">
          <!-- top_k：所有策略通用 -->
          <div class="kb-config-card" :class="{ 'is-disabled': !isActive('top_k') }">
            <div class="kb-card-head">
              <span class="kb-card-title">最大召回数量</span>
              <span class="kb-info">ⓘ
                <span class="kb-tooltip">每次检索最多返回的结果条数。数值越大召回越全但噪声也可能增多，建议 3–10。</span>
              </span>
            </div>
            <input v-model.number="ragForm.top_k" type="number" min="1" max="50" :disabled="!isActive('top_k')" />
          </div>

          <!-- 相似度度量 -->
          <div class="kb-config-card" :class="{ 'is-disabled': !isActive('metric_semantic') }">
            <div class="kb-card-head">
              <span class="kb-card-title">相似度度量</span>
              <span class="kb-info">ⓘ
                <span class="kb-tooltip">向量间的距离计算方式。余弦相似度最常用；点积对向量长度敏感；欧式距离偏向空间邻近。</span>
              </span>
            </div>
            <select v-model="ragForm.semantic.metric" :disabled="!isActive('metric_semantic')">
              <option value="cosine">余弦相似度</option>
              <option value="dot_product">点积</option>
              <option value="euclidean">欧式距离</option>
            </select>
          </div>

          <!-- BM25 最小匹配度 -->
          <div class="kb-config-card" :class="{ 'is-disabled': !isActive('bm25_threshold') }">
            <div class="kb-card-head">
              <span class="kb-card-title">BM25 最小匹配度</span>
              <span class="kb-info">ⓘ
                <span class="kb-tooltip">低于该分数的文档将被丢弃。阈值越高结果越精准但可能漏召回，普通语料 0–10 区间调节。</span>
              </span>
            </div>
            <input v-model.number="ragForm.bm25.min_score_threshold" type="number" step="0.1" :disabled="!isActive('bm25_threshold')" />
          </div>

          <!-- 语义 最小匹配度 -->
          <div class="kb-config-card" :class="{ 'is-disabled': !isActive('semantic_threshold') }">
            <div class="kb-card-head">
              <span class="kb-card-title">语义最小匹配度</span>
              <span class="kb-info">ⓘ
                <span class="kb-tooltip">余弦值低于该阈值视为不相关。范围 0–1，0.7 左右较严格，0.5 更宽松易召回。</span>
              </span>
            </div>
            <input v-model.number="ragForm.semantic.min_score_threshold" type="number" step="0.05" min="0" max="1" :disabled="!isActive('semantic_threshold')" />
          </div>

          <!-- 融合方式 -->
          <div class="kb-config-card" :class="{ 'is-disabled': !isActive('fusion_method') }">
            <div class="kb-card-head">
              <span class="kb-card-title">融合方式</span>
              <span class="kb-info">ⓘ
                <span class="kb-tooltip">混合检索合并两套结果的方式。RRF 按排名倒数加权、无需调权；加权融合需手动设定语义权重。</span>
              </span>
            </div>
            <select v-model="ragForm.hybrid.fusion_method" :disabled="!isActive('fusion_method')">
              <option value="rrf">倒数排序融合 (RRF)</option>
              <option value="weighted">加权融合</option>
            </select>
          </div>

          <!-- 语义权重 -->
          <div class="kb-config-card" :class="{ 'is-disabled': !isActive('weighted_alpha') }">
            <div class="kb-card-head">
              <span class="kb-card-title">语义权重 (α)</span>
              <span class="kb-info">ⓘ
                <span class="kb-tooltip">语义检索在融合中的占比。0.0 偏向关键词，1.0 偏向语义，0.5 为均衡。</span>
              </span>
            </div>
            <input v-model.number="ragForm.hybrid.weighted_alpha" type="number" step="0.05" min="0" max="1" :disabled="!isActive('weighted_alpha')" />
          </div>

          <!-- 混合最小匹配度 -->
          <div class="kb-config-card" :class="{ 'is-disabled': !isActive('hybrid_threshold') }">
            <div class="kb-card-head">
              <span class="kb-card-title">混合最小匹配度</span>
              <span class="kb-info">ⓘ
                <span class="kb-tooltip">融合后综合得分低于该值的文档将被过滤，范围 0–1。</span>
              </span>
            </div>
            <input v-model.number="ragForm.hybrid.min_score_threshold" type="number" step="0.05" min="0" max="1" :disabled="!isActive('hybrid_threshold')" />
          </div>

          <!-- 结果重排 -->
          <div class="kb-config-card" :class="{ 'is-disabled': !isActive('rerank') }">
            <div class="kb-card-head">
              <span class="kb-card-title">结果重排 (Rerank)</span>
              <span class="kb-info">ⓘ
                <span class="kb-tooltip">用更精细的模型对召回结果二次排序，可显著提升相关性，但会增加响应耗时。开启后使用后端默认重排模型。</span>
              </span>
            </div>
            <label class="kb-switch">
              <input v-model="ragForm.rerank.enabled" type="checkbox" :disabled="!isActive('rerank')" />
              <span class="kb-switch-track"><span class="kb-switch-thumb"></span></span>
              <span class="kb-switch-text">{{ ragForm.rerank.enabled ? "已开启" : "已关闭" }}</span>
            </label>
          </div>
        </div>

        <div class="kb-modal-actions">
          <button class="kb-btn kb-btn-ghost" type="button" :disabled="configSaving" @click="cancelRagConfig">
            取消
          </button>
          <button class="kb-btn kb-btn-ghost" type="button" :disabled="configSaving" @click="resetRagConfig">
            重置
          </button>
          <button class="kb-btn kb-btn-primary" type="button" :disabled="configSaving" @click="saveRagConfig">
            {{ configSaving ? "保存中…" : "确认" }}
          </button>
        </div>
      </div>
    </div>

    <section class="kb-list">
      <h2>已上传文件</h2>
      <p v-if="!store.knowledgeFiles.length" class="kb-empty">暂无文件</p>
      <ul v-else class="kb-file-list">
        <li
          v-for="item in store.knowledgeFiles"
          :key="item.id"
          class="kb-file-item"
        >
          <div class="kb-file-meta">
            <span class="kb-file-name">{{ item.name }}</span>
            <span class="kb-file-sub">{{ item.sizeLabel }} · {{ item.typeLabel }} · {{ item.uploadedAt }}</span>
          </div>
          <div class="kb-file-status">
            <span class="kb-status" :class="`is-${item.status}`">
              {{ statusLabel(item) }}
            </span>
            <button
              class="kb-remove"
              type="button"
              @click="store.removeKnowledgeFile(item.id)"
            >
              删除
            </button>
          </div>
          <p v-if="item.error" class="kb-file-error">{{ item.error }}</p>
        </li>
      </ul>
    </section>

    <p v-if="isUploading" class="kb-uploading-tip">正在上传，请稍候…</p>
  </div>
</template>

<style scoped>
.kb-view {
  height: 100%;
  padding: 24px;
  color: #1f2937;
  overflow-y: auto;
}

.kb-header h1 {
  margin: 0;
  font-size: 22px;
}

.kb-subtitle {
  margin: 6px 0 0;
  color: #6b7280;
  font-size: 14px;
}

.kb-stats {
  display: flex;
  gap: 16px;
  margin: 24px 0;
}

.kb-stat {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

.kb-stat-value {
  font-size: 24px;
  font-weight: 600;
}

.kb-stat-value.success { color: #16a34a; }
.kb-stat-value.warning { color: #d97706; }
.kb-stat-value.danger { color: #dc2626; }

.kb-stat-label {
  margin-top: 4px;
  font-size: 13px;
  color: #6b7280;
}

.kb-dropzone {
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  padding: 40px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.kb-dropzone.is-over {
  border-color: #2563eb;
  background: #eff6ff;
}

.kb-dropzone-icon {
  font-size: 28px;
  color: #2563eb;
}

.kb-dropzone-text {
  margin: 10px 0 4px;
  font-size: 15px;
  font-weight: 500;
}

.kb-dropzone-hint {
  margin: 0;
  font-size: 13px;
  color: #9ca3af;
}

.kb-toolbar {
  display: flex;
  align-items: center;
  gap: 32px;
  margin: 20px 0;
  flex-wrap: wrap;
}

.kb-field {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.kb-field select {
  padding: 7px 10px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  background: #fff;
}

.kb-strategy-trigger {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 7px 14px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  font-size: 14px;
  transition: border-color 0.15s, background 0.15s;
}

.kb-strategy-trigger:hover {
  border-color: #2563eb;
  background: #f8faff;
}

.kb-strategy-label {
  color: #6b7280;
}

.kb-strategy-value {
  font-weight: 600;
  color: #111827;
}

.kb-strategy-caret {
  color: #2563eb;
  font-size: 13px;
}

.kb-list h2 {
  font-size: 16px;
  margin: 24px 0 12px;
}

.kb-empty {
  color: #9ca3af;
  font-size: 14px;
}

.kb-file-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.kb-file-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
}

.kb-file-meta {
  display: flex;
  flex-direction: column;
}

.kb-file-name {
  font-weight: 500;
}

.kb-file-sub {
  font-size: 12px;
  color: #9ca3af;
}

.kb-file-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.kb-status {
  font-size: 13px;
  padding: 2px 10px;
  border-radius: 999px;
  background: #f3f4f6;
  color: #4b5563;
}

.kb-status.is-success { background: #dcfce7; color: #166534; }
.kb-status.is-error { background: #fee2e2; color: #991b1b; }
.kb-status.is-uploading { background: #dbeafe; color: #1e40af; }
.kb-status.is-indexing { background: #fef3c7; color: #92400e; }

.kb-remove {
  border: none;
  background: transparent;
  color: #dc2626;
  cursor: pointer;
  font-size: 13px;
}

.kb-file-error {
  margin: 0;
  font-size: 12px;
  color: #dc2626;
}

.kb-uploading-tip {
  margin-top: 16px;
  color: #2563eb;
  font-size: 13px;
}

.kb-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(17, 24, 39, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 24px;
}

.kb-modal {
  width: 100%;
  max-width: 560px;
  max-height: 90vh;
  overflow-y: auto;
  background: #fff;
  border-radius: 14px;
  padding: 22px 24px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2);
}

.kb-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.kb-modal-head h3 {
  margin: 0;
  font-size: 17px;
}

.kb-modal-close {
  border: none;
  background: transparent;
  font-size: 18px;
  color: #6b7280;
  cursor: pointer;
  line-height: 1;
}

.kb-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 22px;
  padding-top: 16px;
  border-top: 1px solid #f0f0f0;
}

.kb-btn {
  padding: 7px 16px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}

.kb-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.kb-btn-primary {
  border: none;
  background: #2563eb;
  color: #fff;
}

.kb-btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
}

.kb-btn-ghost {
  border: 1px solid #d1d5db;
  background: #fff;
  color: #374151;
}

.kb-btn-ghost:hover:not(:disabled) {
  background: #f3f4f6;
}

.kb-strategy-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.kb-strategy-tab {
  flex: 1;
  padding: 9px 0;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  background: #fff;
  color: #374151;
  font-size: 14px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s, color 0.15s;
}

.kb-strategy-tab:hover {
  border-color: #2563eb;
}

.kb-strategy-tab.is-active {
  border-color: #2563eb;
  background: #eff6ff;
  color: #1d4ed8;
  font-weight: 600;
}

.kb-config-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.kb-config-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  transition: opacity 0.15s, background 0.15s;
}

.kb-config-card.is-disabled {
  opacity: 0.45;
  background: #f9fafb;
  pointer-events: none;
}

.kb-config-card.is-disabled .kb-info {
  pointer-events: auto;
}

.kb-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.kb-card-title {
  font-weight: 600;
  color: #111827;
  font-size: 14px;
}

.kb-info {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: #eef2ff;
  color: #4f46e5;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  font-size: 12px;
  line-height: 1;
  cursor: help;
  flex-shrink: 0;
}

.kb-info:hover {
  background: #e0e7ff;
}

.kb-tooltip {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: max(220px, 100%);
  z-index: 20;
  padding: 8px 10px;
  border-radius: 8px;
  background: #1f2937;
  color: #f9fafb;
  font-size: 12px;
  line-height: 1.5;
  text-align: left;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
  opacity: 0;
  visibility: hidden;
  transform: translateY(-4px);
  transition: opacity 0.12s, transform 0.12s, visibility 0.12s;
  pointer-events: none;
}

.kb-info:hover .kb-tooltip {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}

.kb-config-card select,
.kb-config-card input:not(.kb-rerank-model) {
  padding: 7px 10px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  background: #fff;
}

.kb-config-card select:focus,
.kb-config-card input:focus {
  outline: none;
  border-color: #2563eb;
}

.kb-switch {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.kb-switch input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.kb-switch-track {
  position: relative;
  width: 40px;
  height: 22px;
  border-radius: 999px;
  background: #d1d5db;
  transition: background 0.15s;
  flex-shrink: 0;
}

.kb-switch-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
  transition: transform 0.15s;
}

.kb-switch input:checked + .kb-switch-track {
  background: #2563eb;
}

.kb-switch input:checked + .kb-switch-track .kb-switch-thumb {
  transform: translateX(18px);
}

.kb-switch-text {
  font-size: 13px;
  color: #6b7280;
}

@media (max-width: 640px) {
  .kb-config-cards {
    grid-template-columns: 1fr;
  }
}
</style>
