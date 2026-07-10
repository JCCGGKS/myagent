# 工具层（app/business/tools）

`app/business/tools` 封装**供 LLM 函数调用（function calling）的业务工具**。Agent 节点把工具 schema 注册到 LLM 的 `tools` 参数，LLM 返回 `tool_calls` 后由 `ToolExecutor` 按名称分发执行，结果以 `tool` 消息回灌模型，形成 ReAct 闭环。

工具层依赖 `app/business/rag`、`app/business/tools/domain` 等子包，是 `business` 层内面向 Agent 的工具聚合点。

## 单点注册表

所有工具的 **schema + handler** 集中在 `tool_executor.py` 顶部的 `TOOLS` 表中，新增工具只改这一处：

```python
TOOLS: dict[str, dict] = {
    "rag_retrieve":    {"schema": RagRetrieveTool().to_tool_schema(), "handler": "_rag_retrieve"},
    "query_order":      {"schema": _ORDER_SCHEMA,    "handler": "_query_order"},
    "query_logistics":  {"schema": _LOGISTICS_SCHEMA,"handler": "_query_logistics"},
    "create_handoff":   {"schema": _HANDOFF_SCHEMA,  "handler": "_handle_handoff"},
}
# LLM 可能返回的历史别名 → 规范名
TOOL_ALIASES = {
    "order_query": "query_order",
    "logistics": "query_logistics",
    "handoff_service": "create_handoff",
    "request_human": "create_handoff",
}
TOOL_SCHEMAS = {name: spec["schema"] for name, spec in TOOLS.items()}
```

- `schema`：OpenAI `tools` 载荷格式，走 `chat.completions.create(tools=...)`。
- `handler`：`ToolExecutor` 上的方法名，统一签名 `(args: dict, state) -> ToolExecutionResult`。
- `ToolExecutor.__init__` 自动从 `TOOLS` 构建 `self._handlers`；`_execute_one` 先用 `TOOL_ALIASES` 归并别名，再查表分发，查不到返回「未知工具」错误。

`registry.py` 只作为对外 façade，返回供 LLM 使用的 schema 列表：

```python
from app.business.tools.tool_executor import TOOL_SCHEMAS

def build_tool_schemas() -> list[dict]:
    return list(TOOL_SCHEMAS.values())
```

`graph.py` 在装配 `AgentNodeService` 时传入 `tools=build_tool_schemas()`，即完成注册。

## 已落地工具

| 工具名 | handler | 说明 |
| --- | --- | --- |
| `rag_retrieve` | `_rag_retrieve` | 知识库检索（见 `rag_tool.RagRetrieveTool`） |
| `query_order` | `_query_order` | 订单状态查询（依赖 `domain.OrderService`） |
| `query_logistics` | `_query_logistics` | 物流进度查询（依赖 `domain.LogisticsService`） |
| `create_handoff` | `_handle_handoff` | 转人工，创建服务单（依赖 `domain.HandoffService`） |

> 订单 / 物流当前读取 `app/data/` 下的 mock 数据（`orders.json` / `logistics.json`）；转人工依赖对应存储实现。

### rag_tool.py — RAG 检索工具
- `RagRetrieveTool`：封装一次知识检索的完整流程。
  - `run(query)`：`strategy.retrieve → _dedup → (rerank | credibility) → top_k`。
  - `_dedup()`：按 `content` 去重，保留同内容中分数最高的一份。
  - `_apply_credibility()`：未启用 rerank 时，按 `score + DOC_TYPE_CREDIBILITY[doc_type]` 微调排序（`policy 0.05 > faq 0.03 > product 0.02 > help 0.01`）。
  - `_rerank()`：调用 DashScope `RerankClient` 重排；客户端为 `None` 或调用失败时降级为原始顺序，不中断链路。
  - `rerank_enabled=None` 时运行时由 `RagConfig` 决定（支持 `/rag/config` 动态开关）。
  - `top_k` 未显式传入时从环境相关的 `RagConfig` 读取。
  - `name / description / to_tool_schema()`：供 LLM function-calling 使用。
- `get_rag_tool()`：从环境相关的 `RagConfig`（`get_rag_config_service()`，按 `APP_ENV` 解析的目标文件，与 `PUT /rag/config` 同源）读取 `top_k` / `rerank` 配置构建实例。

## 调用关系

```
agent_node.py (AgentNodeService)
  ├─ tools = build_tool_schemas()        # registry.py → tool_executor.TOOL_SCHEMAS
  └─ tool_executor.run(tool_calls, state)
        └─ _execute_one(name, args, state)
              ├─ TOOL_ALIASES 归并别名
              ├─ self._handlers[name] 分发
              ├─ _rag_retrieve    → RagRetrieveTool.run()  → app/business/rag
              ├─ _query_order     → domain.OrderService
              ├─ _query_logistics → domain.LogisticsService
              └─ _handle_handoff  → domain.HandoffService
```

## 新增工具

1. 在 `tool_executor.py` 的 `TOOLS` 表中加一项（`schema` 内联或引用常量）。
2. 实现对应的 handler 方法：`def _your_tool(self, args, state) -> ToolExecutionResult`。
   - `order_id` 等参数优先取 `args.get(...)`，缺省回退 `state.slots.get(...)`。
3. 若依赖外部服务，在 `ToolExecutor.__init__` 增加参数，并在 `graph.py` 注入对应实例。

无需改动 `registry.py` 与 `agent_node.py` —— 它们均从 `TOOLS` 派生。

## 约定
- 工具内部依赖下沉到 `rag` / `domain` / `dao` 等子包，工具层只做编排与契约封装。
- handler 统一签名 `(args, state)`，返回 `ToolExecutionResult`；`create_handoff` 因需写回 `state` 而返回 `state` 本身（已在方法内更新 `state.tool_result`）。
