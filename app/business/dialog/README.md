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
- `MessageService.persist(state, request)`：把用户消息、助手回复（澄清/普通）、工具调用结果写入会话存储；依赖 `SessionService`。
- `_tool_category(state)`：按 `current_action` 区分工具类别（`handoff_human` → `workflow`，其余 → `query`）。

### `session.py` — 会话业务服务（封装 `dao.SessionStore`）
- `SessionService`：对上层暴露稳定接口——
  - 状态读写 `get / save / append_message / record_tool_call`（方法名对齐 `SessionStore`，供 agent / `MessageService` 内部使用）；
  - 会话管理 `list_sessions / get_messages / get_owner / rename / delete / create`（供 api 端点使用）。
- `get_session_service()`：按配置构造默认实现（内存 / MySQL）。
- 存储实现（内存 / MySQL）仍由 `SessionStore` 负责，本模块只做业务层编排，避免上层直接依赖数据访问细节。

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
