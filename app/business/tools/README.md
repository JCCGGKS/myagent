# 工具层（app/business/tools）

`app/business/tools` 封装**供 LLM 调用的业务工具**（Agent 节点通过 `to_tool_schema()` 暴露给模型，经 ReAct 循环调用）。工具层依赖 `app/business/rag` 等子包，是 `business` 层内面向 Agent 的工具聚合点。

## 已落地工具

### rag_tool.py — RAG 检索工具（由 app/business/rag 迁移而来）
- `RagRetrieveTool`：封装一次知识检索的完整流程。
  - `run(query)`：`strategy.retrieve → _dedup → (rerank | credibility) → top_k`。
  - `_dedup()`：按 `content` 去重，保留同内容中分数最高的一份。
  - `_apply_credibility()`：未启用 rerank 时，按 `score + DOC_TYPE_CREDIBILITY[doc_type]` 微调排序（`policy 0.05 > faq 0.03 > product 0.02 > help 0.01`）。
  - `_rerank()`：调用 DashScope `RerankClient` 重排；客户端为 `None` 或调用失败时降级为原始顺序，不中断链路。
  - `rerank_enabled=None` 时运行时由 `RagConfig` 决定（支持 `/rag/config` 动态开关）。
  - `top_k` 未显式传入时从环境相关的 `RagConfig` 读取（不再写死为 5）。
  - `name / description / to_tool_schema()`：供 LLM function-calling 使用。
- `get_rag_tool()`：从环境相关的 `RagConfig`（`get_rag_config_service()`，按 `APP_ENV` 解析的目标文件，与 `PUT /rag/config` 同源）读取 `top_k` / `rerank` 配置构建实例。

### 调用关系
```
agent_node.py (AgentNodeService)
  └─ from app.business.tools.rag_tool import RagRetrieveTool
       └─ RagRetrieveTool.run()
            ├─ RetrievalStrategy   (app/business/rag)   召回
            ├─ RerankClient        (app/business/rag/rerank)  重排（可选）
            └─ DOC_TYPE_CREDIBILITY   去重 + 可信度排序
```

## 新增工具约定
- 每个工具类实现 `run()` 与 `to_tool_schema()`，便于 Agent 节点统一注册。
- 工具内部依赖应下沉到 `rag` / `domain` / `dao` 等子包，工具层只做编排与契约封装。
