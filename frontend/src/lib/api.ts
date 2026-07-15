import type { ChatRequest, ChatResponse, MessageItem } from "@/types/chat";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

const TOKEN_KEY = "myagent_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    // 401：token 过期或无效，清除登录态并跳转登录页
    if (response.status === 401 && !path.startsWith("/auth/")) {
      clearToken();
      localStorage.removeItem("myagent_user");
      window.location.href = "/login";
      throw new Error("登录已过期，请重新登录");
    }

    let detail = "";
    try {
      const body = await response.json();
      detail = body?.detail ?? "";
    } catch {
      detail = await response.text().catch(() => "");
    }
    const err = new Error(detail || `Request failed with status ${response.status}`) as Error & {
      status?: number;
    };
    err.status = response.status;
    throw err;
  }

  return (await response.json()) as T;
}

export function postChat(payload: ChatRequest): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface ChatSessionSummary {
  session_id: string;
  title: string;
  updated_at: string | null;
}

export function getSessionList(): Promise<ChatSessionSummary[]> {
  return request<ChatSessionSummary[]>(`/chat/sessions`);
}

export function getSessionMessages(sessionId: string): Promise<MessageItem[]> {
  return request<MessageItem[]>(`/chat/session/${sessionId}/messages`);
}

export function updateSession(sessionId: string, title: string): Promise<void> {
  return request<void>(`/chat/session/${sessionId}`, {
    method: "PUT",
    body: JSON.stringify({ title }),
  });
}

export function deleteSession(sessionId: string): Promise<void> {
  return request<void>(`/chat/session/${sessionId}`, {
    method: "DELETE",
  });
}

export interface KnowledgeUploadResult {
  id: number;
  user_id: number;
  filename: string;
  file_size: number;
  doc_type: string;
  chunk_count: number;
  status: 0 | 1 | 2;
  error_message: string | null;
  content_hash: string | null;
  created_at: string | null;
  updated_at: string | null;
  // 幂等命中：同一用户上传相同内容，服务端跳过向量化直接返回已有记录
  duplicated?: boolean;
}

// 知识库文件列表（GET /knowledge/files）
export interface KnowledgeFileRecord {
  id: number;
  user_id: number;
  filename: string;
  file_size: number;
  doc_type: string;
  chunk_count: number;
  status: 0 | 1 | 2;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
}

// 列出当前用户的知识库文件（按上传时间倒序）
export function getKnowledgeFiles(): Promise<KnowledgeFileRecord[]> {
  return request<KnowledgeFileRecord[]>("/knowledge/files");
}

// 删除知识库文件（软删除元信息 + 清向量）
export function deleteKnowledgeFile(docId: number): Promise<void> {
  return request<void>(`/knowledge/files/${docId}`, {
    method: "DELETE",
  });
}

// 知识库文件上传（multipart/form-data）
export async function uploadKnowledgeFile(
  file: File,
  docType: string,
): Promise<KnowledgeUploadResult> {
  const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";
  const formData = new FormData();
  formData.append("file", file);
  formData.append("doc_type", docType);

  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`${API_BASE}/knowledge/upload`, {
    method: "POST",
    body: formData,
    headers,
  });
  if (!response.ok) {
    if (response.status === 401) {
      clearToken();
      localStorage.removeItem("myagent_user");
      window.location.href = "/login";
      throw new Error("登录已过期，请重新登录");
    }
    const detail = await response.text().catch(() => "");
    throw new Error(`上传失败 (${response.status}): ${detail}`);
  }
  return (await response.json()) as KnowledgeUploadResult;
}

// 更新已上传的知识库文件（multipart/form-data）：删除旧向量 + 重建 + 刷新上传时间。
// doc_type 以表单字段传入（与上传一致），无默认值，由调用方（下拉选择）提供。
export async function updateKnowledgeFile(
  docId: number,
  file: File,
  docType: string,
): Promise<KnowledgeUploadResult> {
  const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";
  const formData = new FormData();
  formData.append("file", file);
  formData.append("doc_type", docType);

  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`${API_BASE}/knowledge/files/${docId}`, {
    method: "PUT",
    body: formData,
    headers,
  });
  if (!response.ok) {
    if (response.status === 401) {
      clearToken();
      localStorage.removeItem("myagent_user");
      window.location.href = "/login";
      throw new Error("登录已过期，请重新登录");
    }
    const detail = await response.text().catch(() => "");
    throw new Error(`更新失败 (${response.status}): ${detail}`);
  }
  return (await response.json()) as KnowledgeUploadResult;
}

// 知识库可上传的文档类型，与后端分块策略（FORMAT_STRATEGIES）对齐。
// 每个类型绑定其对应的文件后缀，供前端下拉选择与上传校验使用。
export interface DocTypeOption {
  value: string;
  label: string;
  extensions: string[];
}

export const DOC_TYPE_OPTIONS: DocTypeOption[] = [
  { value: "markdown", label: "Markdown 文档", extensions: [".md", ".markdown"] },
  { value: "json", label: "JSON 数据", extensions: [".json"] },
  { value: "word", label: "Word 文档", extensions: [".docx", ".doc"] },
  { value: "excel", label: "Excel 表格", extensions: [".xlsx", ".xls"] },
  { value: "csv", label: "CSV 表格", extensions: [".csv"] },
  { value: "pdf", label: "PDF 文档", extensions: [".pdf"] },
  { value: "ppt", label: "PPT 演示文稿", extensions: [".pptx", ".ppt"] },
];

const DOC_TYPE_EXTENSION_MAP: Record<string, string[]> = Object.fromEntries(
  DOC_TYPE_OPTIONS.map((o) => [o.value, o.extensions]),
);

// 判断文件后缀是否属于指定文档类型允许的扩展名。
export function isExtensionAllowed(fileName: string, docType: string): boolean {
  const ext = fileName.includes(".")
    ? fileName.slice(fileName.lastIndexOf(".")).toLowerCase()
    : "";
  const allowed = DOC_TYPE_EXTENSION_MAP[docType] ?? [];
  return allowed.includes(ext);
}

// 取文档类型对应的展示标签（用于上传校验提示等）。
export function docTypeLabel(docType: string): string {
  return DOC_TYPE_OPTIONS.find((o) => o.value === docType)?.label ?? docType;
}

export interface RagConfig {
  retrieval_strategy: "bm25" | "semantic" | "hybrid";
  top_k: number;
  // 单一最小匹配度阈值：读出即用，不做归一化映射。
  // 不同策略适用量纲不同，由前端按 retrieval_strategy 控制可输入范围。
  min_score_threshold: number;
  // 切块参数（入库时使用，影响检索质量）
  chunk_size: number;
  chunk_overlap: number;
  min_chunk_size: number;
  // RRF 融合常数 k（仅 hybrid 生效）
  rrf_k: number;
  rerank: { enabled: boolean; model: string };
}

export function getRagConfig(): Promise<RagConfig> {
  return request<RagConfig>("/rag/config");
}

export function updateRagConfig(patch: Partial<RagConfig>): Promise<RagConfig> {
  return request<RagConfig>("/rag/config", {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

// ---- 认证 ----
export interface AuthUser {
  id: number;
  username: string;
  email: string;
}

export interface AuthToken {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export function postRegister(payload: { username: string; email: string; password: string }): Promise<AuthUser> {
  return request<AuthUser>("/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function postLogin(payload: { username: string; password: string }): Promise<AuthToken> {
  return request<AuthToken>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function postForgotPassword(payload: { email: string }): Promise<{ detail: string }> {
  return request<{ detail: string }>("/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function postResetPassword(payload: { token: string; new_password: string }): Promise<{ detail: string }> {
  return request<{ detail: string }>("/auth/reset-password", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function postChangePassword(payload: { old_password: string; new_password: string }): Promise<{ detail: string }> {
  return request<{ detail: string }>("/auth/change-password", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
