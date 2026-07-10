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
| `dialog/` | 澄清 + 回复生成 + 消息落库 | `dialog.py` (`ClarificationService` / `ResponseService` / `MessageService`) |
| `memory/` | 对话记忆（占位） | 仅保留目录，真正的记忆能力后续实现；消息落库属于 `dialog` 模块 |
| `rag/` | 知识检索 | `chunker` / `ingestion` / `sparse_bm25` / `retrieval_strategy` / `rerank` |
| `prompts/` | LLM prompt 定义 | intent / clarification / response / agent 等 |
| `auth/` | 认证业务 | service / router / models / deps |

## 执行链

```
input_normalizer -> intent_router -> state_tracker -> policy_layer
    -> clarification / agent_node / handoff -> response_generator
    -> context_compressor -> message_writer
```

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
