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

const strategyLabel = computed(() => {
  switch (ragForm.retrieval_strategy) {
    case "bm25":
      return "关键词检索";
    case "semantic":
      return "语义向量检索";
    case "hybrid":
      return "混合检索";
    default:
      return String(ragForm.retrieval_strategy);
  }
});

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

        <div class="kb-form-grid">
          <label class="kb-field-col">
            <span>检索策略</span>
            <select v-model="ragForm.retrieval_strategy">
              <option value="bm25">关键词检索 (BM25)</option>
              <option value="semantic">语义向量检索</option>
              <option value="hybrid">混合检索</option>
            </select>
          </label>

          <label class="kb-field-col">
            <span>最大召回数量 (top_k)</span>
            <input v-model.number="ragForm.top_k" type="number" min="1" max="50" />
          </label>

          <label v-if="ragForm.retrieval_strategy === 'semantic' || ragForm.retrieval_strategy === 'hybrid'" class="kb-field-col">
            <span>相似度度量</span>
            <select v-model="ragForm.semantic.metric">
              <option value="cosine">余弦相似度</option>
              <option value="dot_product">点积</option>
              <option value="euclidean">欧式距离</option>
            </select>
          </label>

          <label v-if="ragForm.retrieval_strategy === 'bm25'" class="kb-field-col">
            <span>最小匹配度 (BM25)</span>
            <input v-model.number="ragForm.bm25.min_score_threshold" type="number" step="0.1" />
          </label>

          <label v-if="ragForm.retrieval_strategy === 'semantic'" class="kb-field-col">
            <span>最小匹配度 (语义)</span>
            <input v-model.number="ragForm.semantic.min_score_threshold" type="number" step="0.05" min="0" max="1" />
          </label>

          <template v-if="ragForm.retrieval_strategy === 'hybrid'">
            <label class="kb-field-col">
              <span>融合方式</span>
              <select v-model="ragForm.hybrid.fusion_method">
                <option value="rrf">倒数排序融合 (RRF)</option>
                <option value="weighted">加权融合</option>
              </select>
            </label>
            <label v-if="ragForm.hybrid.fusion_method === 'weighted'" class="kb-field-col">
              <span>语义权重 (α)</span>
              <input v-model.number="ragForm.hybrid.weighted_alpha" type="number" step="0.05" min="0" max="1" />
            </label>
            <label class="kb-field-col">
              <span>最小匹配度 (混合)</span>
              <input v-model.number="ragForm.hybrid.min_score_threshold" type="number" step="0.05" min="0" max="1" />
            </label>
          </template>
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

.kb-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 20px;
}

.kb-field-col {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: #374151;
}

.kb-field-col select,
.kb-field-col input {
  padding: 7px 10px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  background: #fff;
}

.kb-field-col select:focus,
.kb-field-col input:focus {
  outline: none;
  border-color: #2563eb;
}

@media (max-width: 640px) {
  .kb-form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
