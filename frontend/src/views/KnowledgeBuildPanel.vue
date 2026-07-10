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
const errorModal = ref({ visible: false, title: "", message: "" });

function showError(title: string, message: string) {
  errorModal.value = { visible: true, title, message };
}

function closeError() {
  errorModal.value.visible = false;
}

function isValidExtension(fileName: string): boolean {
  const ext = fileName.split(".").pop()?.toLowerCase() || "";
  return ["md", "markdown", "json"].includes(ext);
}

const uploading = ref(false);
const isUploading = computed(() => uploading.value);

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
  // 切块参数与 top_k / 阈值对所有策略通用（切块在入库时生效，与检索策略无关）
  const set = new Set<string>(["top_k", "threshold", "chunk_size", "chunk_overlap", "min_chunk_size"]);
  if (s === "hybrid") {
    set.add("rerank");
    set.add("rrf_k");
  }
  return set;
});

// 最小匹配度阈值的可输入范围与提示：由前端按检索策略控制（量纲不同）。
const thresholdAttrs = computed<{ min: number; max: number; step: number; hint: string }>(() => {
  switch (ragForm.retrieval_strategy) {
    case "bm25":
      return {
        min: 0,
        max: 10,
        step: 0.1,
        hint: "BM25 原始分数，0~10 量级，强命中约 4~6。阈值越高越精准但可能漏召回。",
      };
    case "semantic":
      return {
        min: 0,
        max: 1,
        step: 0.05,
        hint: "余弦相似度，0~1。0.7 左右较严格，0.5 更宽松易召回。",
      };
    case "hybrid":
      return {
        min: 0,
        max: 0.05,
        step: 0.001,
        hint: "RRF 融合分数约 1/(k+rank)，k=60 时最大 ~0.016；必须接近 0，否则会过滤掉全部结果。",
      };
    default:
      return { min: 0, max: 1, step: 0.05, hint: "" };
  }
});

// 每项解释是否“激活”（用于置灰判断）
function isActive(key: string) {
  return activeFields.value.has(key);
}

// ---- 检索配置 ----
const defaultConfig: RagConfig = {
  retrieval_strategy: "hybrid",
  top_k: 5,
  min_score_threshold: 0.0,
  chunk_size: 800,
  chunk_overlap: 100,
  min_chunk_size: 50,
  rrf_k: 60,
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
  ragForm.min_score_threshold = next.min_score_threshold;
  ragForm.chunk_size = next.chunk_size;
  ragForm.chunk_overlap = next.chunk_overlap;
  ragForm.min_chunk_size = next.min_chunk_size;
  ragForm.rrf_k = next.rrf_k;
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

onMounted(() => {
  loadRagConfig();
  store.fetchKnowledgeFiles();
});

function triggerUpload() {
  fileInput.value?.click();
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = input.files;
  if (!files?.length) return;

  const invalid = Array.from(files).filter((file) => !isValidExtension(file.name));
  if (invalid.length) {
    const names = invalid.map((f) => f.name).join(", ");
    showError(
      "文件类型不支持",
      `以下文件不是允许的格式，请上传 .md / .markdown / .json：\n${names}`,
    );
    input.value = "";
    return;
  }

  uploading.value = true;
  store.uploadKnowledgeFiles(files, docType.value).finally(() => {
    uploading.value = false;
    input.value = "";
  });
}

function onDrop(event: DragEvent) {
  dragOver.value = false;
  const files = event.dataTransfer?.files;
  if (!files?.length) return;

  const invalid = Array.from(files).filter((file) => !isValidExtension(file.name));
  if (invalid.length) {
    const names = invalid.map((f) => f.name).join(", ");
    showError(
      "文件类型不支持",
      `以下文件不是允许的格式，请上传 .md / .markdown / .json：\n${names}`,
    );
    return;
  }

  uploading.value = true;
  store.uploadKnowledgeFiles(files, docType.value).finally(() => {
    uploading.value = false;
  });
}

function statusLabel(item: KnowledgeFileItem): string {
  switch (item.status) {
    case 0:
      return "处理中";
    case 1:
      return item.chunk_count ? `已入库 ${item.chunk_count} 块` : "已入库";
    case 2:
      return "失败";
    default:
      return "未知";
  }
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function formatTime(iso: string | null): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

async function onRemove(id: number) {
  try {
    await store.removeKnowledgeFile(id);
  } catch (error) {
    showError("删除失败", error instanceof Error ? error.message : String(error));
  }
}
</script>

<template>
  <div class="kb-view">
    <header class="kb-header">
      <h1>知识库构建</h1>
      <p class="kb-subtitle">上传 Markdown / JSON 文档，自动分块并写入向量库。</p>
    </header>

    <section class="kb-toolbar">
      <label class="kb-field">
        <select v-model="docType">
          <option value="markdown">文档类型：Markdown</option>
          <option value="json">文档类型：JSON</option>
        </select>
      </label>

      <button class="kb-strategy-trigger" type="button" @click="showConfigModal = true">
        <span class="kb-strategy-label">检索策略</span>
        <span class="kb-strategy-value">{{ strategyLabel }}</span>
        <span class="kb-strategy-caret">⚙</span>
      </button>

      <button class="kb-upload-btn" type="button" @click="triggerUpload">
        ⬆ 上传文件
      </button>
    </section>

    <section
      class="kb-dropzone"
      :class="{ 'is-over': dragOver }"
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
      <p class="kb-dropzone-text">拖拽文件到此处上传</p>
      <p class="kb-dropzone-hint">支持 .md / .markdown / .json</p>
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

          <!-- 最小匹配度（单一字段，按检索策略动态范围） -->
          <div class="kb-config-card" :class="{ 'is-disabled': !isActive('threshold') }">
            <div class="kb-card-head">
              <span class="kb-card-title">最小匹配度</span>
              <span class="kb-info">ⓘ
                <span class="kb-tooltip">{{ thresholdAttrs.hint }}</span>
              </span>
            </div>
            <input
              v-model.number="ragForm.min_score_threshold"
              type="number"
              :step="thresholdAttrs.step"
              :min="thresholdAttrs.min"
              :max="thresholdAttrs.max"
              :disabled="!isActive('threshold')"
            />
          </div>

          <!-- RRF 常数 k（仅 hybrid 生效） -->
          <div class="kb-config-card" :class="{ 'is-disabled': !isActive('rrf_k') }">
            <div class="kb-card-head">
              <span class="kb-card-title">RRF 常数 k</span>
              <span class="kb-info">ⓘ
                <span class="kb-tooltip">混合检索 RRF 融合的常数 k，分母 1/(k+rank)。k 越大头部权重越集中，越小则尾部越有机会；典型 40–100，默认 60。仅 hybrid 策略生效。</span>
              </span>
            </div>
            <input v-model.number="ragForm.rrf_k" type="number" min="1" max="200" step="1" :disabled="!isActive('rrf_k')" />
          </div>

          <!-- 切块大小（入库参数，对所有策略生效） -->
          <div class="kb-config-card" :class="{ 'is-disabled': !isActive('chunk_size') }">
            <div class="kb-card-head">
              <span class="kb-card-title">切块大小 (chunk_size)</span>
              <span class="kb-info">ⓘ
                <span class="kb-tooltip">入库时每个文本块的最大字符数。越小粒度越细、命中越精确但上下文越少；建议 400–1200。</span>
              </span>
            </div>
            <input v-model.number="ragForm.chunk_size" type="number" min="50" max="4000" step="50" :disabled="!isActive('chunk_size')" />
          </div>

          <!-- 切块重叠（入库参数） -->
          <div class="kb-config-card" :class="{ 'is-disabled': !isActive('chunk_overlap') }">
            <div class="kb-card-head">
              <span class="kb-card-title">切块重叠 (overlap)</span>
              <span class="kb-info">ⓘ
                <span class="kb-tooltip">硬切时相邻块保留的重叠字符数，避免句子被截断丢上下文；应小于 chunk_size，通常 50–200。</span>
              </span>
            </div>
            <input v-model.number="ragForm.chunk_overlap" type="number" min="0" max="1000" step="10" :disabled="!isActive('chunk_overlap')" />
          </div>

          <!-- 最小块长度（入库参数） -->
          <div class="kb-config-card" :class="{ 'is-disabled': !isActive('min_chunk_size') }">
            <div class="kb-card-head">
              <span class="kb-card-title">最小块长度</span>
              <span class="kb-info">ⓘ
                <span class="kb-tooltip">硬切时丢弃短于此长度的碎块，避免噪声；应小于 chunk_size，通常 20–100。</span>
              </span>
            </div>
            <input v-model.number="ragForm.min_chunk_size" type="number" min="1" max="1000" step="10" :disabled="!isActive('min_chunk_size')" />
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

    <!-- 通用错误提示弹窗 -->
    <div v-if="errorModal.visible" class="kb-modal-mask" @click.self="closeError">
      <div class="kb-modal" style="max-width: 420px;">
        <div class="kb-modal-head">
          <h3>{{ errorModal.title }}</h3>
          <button class="kb-modal-close" type="button" @click="closeError">✕</button>
        </div>
        <p class="kb-error-message">{{ errorModal.message }}</p>
        <div class="kb-modal-actions">
          <button class="kb-btn kb-btn-primary" type="button" @click="closeError">知道了</button>
        </div>
      </div>
    </div>

    <section class="kb-list">
      <ul v-if="store.knowledgeFiles.length" class="kb-file-list">
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
  padding: 28px;
  text-align: center;
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
  gap: 16px;
  margin: 24px 0 16px;
  flex-wrap: wrap;
}

.kb-upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  border: none;
  border-radius: 8px;
  background: #2563eb;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.15s;
}

.kb-upload-btn:hover {
  background: #1d4ed8;
}

.kb-dropzone {
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  padding: 28px;
  text-align: center;
  transition: border-color 0.15s, background 0.15s;
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

.kb-error-message {
  white-space: pre-line;
  line-height: 1.6;
  color: #374151;
  font-size: 14px;
  margin: 0 0 8px;
}

.kb-error-message + .kb-modal-actions {
  margin-top: 16px;
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
