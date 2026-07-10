# app/business/dialog 模块

对话产出层：澄清话术生成、最终回复生成、消息落库与会话服务。
原 `app/business/dialog.py` 按职责拆分为以下文件，统一由 `__init__.py` 再导出。

## 文件职责

### `clarification.py` — 澄清话术生成
- `ClarificationPromptRegistry`：从 `config/clarification_prompts.yml` 加载**示例配置**（含 `slot_clarification` 子项）。
- `ClarificationService.generate(state)`：优先走 LLM 生成追问话术；把 yml 全部示例按配置驱动整理后注入提示词（新增键无需改代码）。无 LLM client 时回退模板。
- 提示词的**定义与构造**不在本文件，而在 `app/business/prompts/`（`build_clarification_system_prompt`）；本模块只加载示例配置并调用该构造器。

### `response.py` — 最终回复生成
- `ResponsePromptRegistry`：从 `config/response_prompts.yml` 加载**示例配置**。
- `ResponseService.generate(state)`：若 `state.reply` 已由 `agent_node` 生成则直接返回；否则组装 `running_summary + recent_messages` 上下文，把 yml 全部示例注入提示词后调用 LLM 生成回复，失败兜底统一道歉语。
- 提示词的**定义与构造**同样在 `app/business/prompts/`（`build_response_system_prompt`）；本模块负责示例注入与调用时机，不持有提示词模板本身。

### `message.py` — 对话消息持久化
- `MessageService.persist(state, request)`：把用户消息、助手回复（澄清/普通）写入会话存储；依赖 `SessionService`。工具调用结果由 `tools/ToolExecutor` 处理，不在此落库。

### `session.py` — 会话业务服务（封装 `dao.SessionStore`）
- `SessionService`：对上层暴露稳定接口——
  - 状态读写 `get / save / append_message`（方法名对齐 `SessionStore`，供 agent / `MessageService` 内部使用）；
  - 会话管理 `list_sessions / get_messages / get_owner / rename / delete / create`（供 api 端点使用）。
- `get_session_service()`：按配置构造默认实现（内存 / MySQL）。
- 存储实现（内存 / MySQL）仍由 `SessionStore` 负责，本模块只做业务层编排，避免上层直接依赖数据访问细节。

## 会话 ID 方案

- **生成（前端）**：新建会话时由前端 `frontend/src/lib/session.ts` 的 `generateSessionId()` 用 `crypto.randomUUID()` 本地生成，作为全局唯一 id；无后端 `/chat/init` 前置调用。
- **传递**：随请求体 `ChatRequest.session_id` 经 `/chat`、`/chat/stream` 发给后端（首条消息即带上）。
- **后端惰性建会话**：`agent/graph.py` 的 `_build_payload` 用 `store.get(session_id) or ConversationState(...)`，`SessionStore.save` 用 `setdefault` 自动建记录——未知 id 不报错，首次收到即建会话。
- **读写入口**：`SessionService`（`session.py`）是上层访问会话数据的唯一入口；`MessageService` 与 `CustomerServiceAgent` 均经它读写。
- **标题兜底**：惰性建会话时不带 title，后端 `list_sessions` 对缺失 title 默认返回 `"新会话"`。
- 已移除：`/chat/init` 接口、`postChatInit`、`SessionInitRequest/Response`，以及 `web-` / `sess-` 双前缀混用（前端统一用 UUID）。

## 分层与依赖

- 依赖方向：`dialog → dao / schema / prompts / utils`（向下、无环）。
- `MessageService` 与 `CustomerServiceAgent` 均通过 `SessionService` 访问会话数据，不直接持有 `SessionStore`。
- 外部统一从包入口导入，例如：

```python
from app.business.dialog import (
    ClarificationService,
    ResponseService,
    MessageService,
    SessionService,
    get_session_service,
)
```
