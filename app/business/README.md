# app/business 模块结构

业务逻辑层，串联意图识别、状态更新、策略分发、工具路由、澄清与回复生成。
分层依赖方向严格向下、无环：`api → business → dao → model`，`pkgs / utils / schema / data` 为叶子层。

## 目录划分

| 目录 | 职责 | 关键符号 |
| --- | --- | --- |
| `agent/` | 运行编排 + ReAct 节点 | `graph.py` (`CustomerServiceAgent` 主图)、`agent_node.py` (`AgentNodeService` 单轮 Agent/ReAct 节点) |
| `tools/` | 工具执行层 | `tool_executor.py` (`ToolExecutor` 统一工具执行，直接驱动 domain 服务)、`domain.py` (`OrderService` / `LogisticsService` / `HandoffService` / `extract_order_id`)、`rag_tool.py` (`RagRetrieveTool`) |
| `context/` | 上下文窗口 + 压缩 + 共享摘要 | `context.py` (`ContextService` 最近消息窗口与压缩)、`state_summary.py` (`build_state_summary` 共享状态摘要，打破 context↔routing 循环依赖) |
| `intent/` | 意图识别 + 状态跟踪 + 策略 | `routing.py` (`IntentRouterService` / `StateTrackerService` / `HandoffClarificationPolicy`)、`schema.py` (`IntentSchemaRegistry` / `IntentRuleRegistry`，默认从 YAML 加载)、`llm_fallback.py` (`LLMIntentFallbackService`) |
| `dialog/` | 澄清 + 回复生成 + 消息落库 + 会话服务 | `clarification.py` (`ClarificationService` / `ClarificationPromptRegistry`)、`response.py` (`ResponseService` / `ResponsePromptRegistry`)、`message.py` (`MessageService`)、`session.py` (`SessionService` 封装 dao 层 `SessionStore`)；提示词定义见 `prompts/` |

### dialog/ 子模块各文件职责

- **`clarification.py`** — 澄清话术生成。
  - `ClarificationPromptRegistry`：从 `config/clarification_prompts.yml` 加载**示例配置**（含 `slot_clarification` 子项）。
  - `ClarificationService.generate(state)`：优先走 LLM 生成追问话术；把 yml 全部示例按配置驱动整理后注入提示词（新增键无需改代码）。无 LLM client 时回退模板。提示词定义本身在 `prompts/`（`build_clarification_system_prompt`），本模块只加载示例并调用构造器。
- **`response.py`** — 最终回复生成。
  - `ResponsePromptRegistry`：从 `config/response_prompts.yml` 加载**示例配置**。
  - `ResponseService.generate(state)`：若 `state.reply` 已由 `agent_node` 生成则直接返回；否则组装 `running_summary + recent_messages` 上下文，把 yml 全部示例注入提示词后调用 LLM 生成回复，失败兜底统一道歉语。提示词定义本身在 `prompts/`（`build_response_system_prompt`）。
- **`message.py`** — 对话消息持久化。
  - `MessageService.persist(state, request)`：把用户消息、助手回复（澄清/普通）写入会话存储；依赖 `SessionService`。工具调用结果由 `tools/ToolExecutor` 处理，不在此落库。
- **`session.py`** — 会话业务服务（封装 `dao.SessionStore`）。
  - `SessionService`：对上层暴露稳定接口——状态读写 `get/save/append_message`（方法名对齐 `SessionStore`，供 agent / `MessageService` 内部使用），以及会话管理 `list_sessions/get_messages/get_owner/rename/delete/create`（供 api 端点使用）。
  - `get_session_service()`：按配置构造默认实现（内存 / MySQL）。
  - 存储实现（内存 / MySQL）仍由 `SessionStore` 负责，本模块只做业务层编排，避免上层直接依赖数据访问细节。
| `memory/` | 对话记忆（占位） | 仅保留目录，真正的记忆能力后续实现；消息落库属于 `dialog` 模块 |
| `rag/` | 知识检索 | `chunking/`（分块策略）/ `bm25.py`（BM25 单一模块：分词 + 稀疏向量 + 手搓倒排索引 + 检索策略）/ `retrieval/`（检索策略）/ `ingestion` |
| `prompts/` | LLM prompt 定义 | intent / clarification / response / agent 等 |
| `auth/` | 认证业务 | service / router / models / deps |

## 执行链

```
input_normalizer -> intent_router -> state_tracker -> policy_layer
    -> clarification / agent_node / handoff -> response_generator
    -> context_compressor
```

- 图到 `context_compressor` 即结束；消息落库不在图内。`CustomerServiceAgent.chat` / `chat_events` 在图运行结束后调用 `MessageService.persist` 批量写入（用户消息 + 助手回复 + 状态快照），保持图作为纯状态机、无副作用、可被 checkpointer 重放。

- `intent_router` 由 `intent/` 驱动；`agent_node` 内含 ReAct 工具循环，经 `tools/ToolExecutor` 执行工具。
- `ToolExecutor` 是**服务**而非图节点：ReAct 循环留在 `agent_node.run` 内，避免跨节点 `agent_thread` / `pending_tool_calls` 序列化。
- `domain.py` 是被 `ToolExecutor` 最终调用的业务查询实现，仅依赖 `app.schema` 与 `app.dao.data`，无回边。

## 包导入约定

`app/business/__init__.py` 统一再导出各子包符号，常见写法：

```python
from app.business.agent import CustomerServiceAgent
from app.business.intent.routing import IntentRouterService, StateTrackerService
from app.business.context import ContextService
from app.business.dialog import MessageService, ClarificationService, ResponseService
from app.business.tools import ToolExecutor
```

`context` / `dialog` / `intent` / `agent` 均为包，旧的文件级导入
（`app.business.context`、`app.business.dialog` 等）仍可继续使用。

## 历史归属说明

早期平铺在 `app/business/` 下的独立文件已按职责迁移：

- `graph.py` / `agent_node.py` → `agent/`
- `domain.py` → `tools/`（合并原 `execution.py` 的 `ExecutionService` 后，统一由 `ToolExecutor` 持有 domain 服务）
- `routing.py` / `intent_schema.py` / `llm_fallback.py` → `intent/`（其中 `intent_schema.py` 改名 `schema.py`）
- `context.py` / `state_summary.py` → `context/`
- `dialog.py` → `dialog/`（升级为包）
- `execution.py` / `memory.py` 已删除（`memory.py` 为孤儿，`MessageService` 归入 `dialog`）
