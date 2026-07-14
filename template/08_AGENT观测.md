# 08 Agent 观测：三层协作（日志 / 事件流 / 指标）

> 设计依据：`plans/observability-trace-plan.md`。本项目采用**方案 C**：在现有 SSE 事件流 + DB 落库骨架上，补 `trace_id` 贯穿、事件回放（event_log）与指标聚合（metrics），零外部 SaaS 依赖。

## 1. 核心模型：三层各管一段

| 层 | 管什么 | 回答的问题 | 落点 |
|---|---|---|---|
| **Logs** | 计划外 / 兜底 / 系统级异常 | 「系统还健不健康、出了什么岔子」 | 分模块文件 `logs/<module>-*.log` |
| **event_log** | 单请求决策链回放 | 「这一轮为什么这么答」 | `event_log` 表 + `GET /chat/session/{id}/events?trace_id=` |
| **Metrics** | 聚合趋势 / 告警 | 「哪里有问题、多严重」 | `/metrics` 端点（Prometheus + Grafana） |

三者**互补不替代**：metrics 预警「宏观哪里坏」→ logs 拿 `trace_id` → event_log 回放「微观怎么决策的」。

## 2. trace_id：贯穿三层的核心 pivot

- 入口（`chat` / `chat_stream`）用 `uuid.uuid4().hex` 生成 `trace_id`，写入 `request`，透传给 `agent.chat/chat_events`。
- 链路内所有节点共享同一 id：
  - **logs**：`app/utils/trace.py:TraceIdFilter` 注入每行 `[tid=...]`，无请求上下文记 `-`。
  - **event_log**：每条事件带 `trace_id` 列。
- 还原单次请求：`grep 'tid=xxx' logs/*.log`；单模块内只看某环节：`grep '\[tool\]' logs/tool-*.log`。

## 3. 第一层：日志（Logs）

- **分模块独立文件**（已落地）：每个模块用 `logging.getLogger("myagent.<module>")`，`setup_logging` 为 `graph / intent / agent / tool / rag / response / context / api / auth` 各注册一份每日滚动文件 `logs/<module>-YYYY-MM-DD.log`，同时冒泡 root 控制台。
- 每行格式：`时间 [级别] myagent.<module> [tid=...] - [tag] 消息`。
- `[tag]` 分段：`[api]`/`[auth]`/`[rag]`（接口层）、`[intent]`/`[tool]`/`[state]`/`[policy]`/`[agent]`/`[handoff]`/`[response]`/`[compressor]`/`[persist]`/`[infra]`（pipeline）。
- 职责边界：**只进日志**——基础设施异常（Redis→MemorySaver 回退、LLM 超时）、未预料的异常栈、降级、观测自身失败（`persist_failed`）、启动/健康检查。这些不是「决策事件」，事件流覆盖不到。

## 4. 第二层：事件流（event_log）

- 表结构（`app/model/session.py:EventLog`）：`id / session_id / trace_id / turn / type / payload(JSON) / created_at`。
- 事件类型（图节点埋点）：
  - `intent`（main/sub/confidence/slots/needs_clarification）
  - `state`（stage/slots/missing_slots/继承结果）
  - `tool_result`（name/args/ok/error/latency_ms/retry 三要素）
  - `final`（reply + session_state 快照）
  - `error`（node + input + 入参，异常时）
- 落库：`MessageService.persist_events` 在图跑完后 **best-effort** 批量写；与「先 persist 再下发 final」时序解耦——失败仅 `logger.warning`，**绝不阻断 final 下发**（见 `app/business/dialog/message.py`）。
- 回放：`GET /chat/session/{session_id}/events?trace_id=` 复用 `session_service.get_owner` 鉴权，防越权读他人会话。
- 用途：单请求「intent → state → tool_result → final」决策链可完整回放，定位哪步出错。

## 5. 第三层：指标（Metrics）

- 自托管 `prometheus-client`（`app/utils/metrics.py`），`app/api/app.py` 暴露 `GET /metrics`（已加入 `middleware/auth.py:PUBLIC_PATHS` 放行，供抓取）。
- 已埋点（label 严格低基数）：
  - `ToolExecutor.run`：`myagent_tool_calls_total{tool_name,status}`、`myagent_tool_latency_seconds{tool_name}`
  - `create_handoff`：`myagent_handoff_total`（业务 KPI：转人工率）
  - intent 事件：`myagent_low_confidence_total`（低置信/需澄清计数）
  - 入口：`myagent_requests_total{intent,channel}`、`myagent_request_latency_seconds`
- 容器：`monitoring/prometheus.yml` + `monitoring/grafana/`，`docker-compose.yml` 加 `prometheus(9090)` / `grafana(3000)`。
- **基数铁律**：label 只放 `intent`/`tool_name`/`node`/`status`/`model`；**`user_id`/`session_id`/原始 prompt 禁入**（高基数会撑爆存储），它们归 trace/event_log，靠 `trace_id` 关联。
- 告警围绕业务 KPI：转人工率突增、低置信率突增、工具失败率、端到端 P99 超界。

## 6. 三层协作与排障路径

```
Metrics 告警：tool=query_order 失败率 5min 内 30% ↑
   └─▶ Logs：grep "tool_result error" + 时间窗 → 拿到 trace_id
        └─▶ event_log：按 trace_id 回放 → 看到 args 超时 / 入参错 / 依赖挂了
```

## 7. 分工原则（落地时遵循）

- **进 event_log**：意图、状态快照、工具调用三要素、final 终态、决策点（policy）依据——一切「已知的业务语义」。
- **只进日志**：基础设施异常、未预料的异常栈、降级/回退、观测自身失败（`persist_failed`）、启动/健康检查——一切「已知的系统异常」与「计划外」。
- **两者都带 `trace_id`**，确保可互相 pivot。

## 8. 代码索引

| 能力 | 位置 |
|---|---|
| trace_id 注入 / 过滤 | `app/utils/trace.py:TraceIdFilter`；入口 `app/api/chat.py` |
| 分模块日志配置 | `app/config/logging_config.py:setup_logging`；`app/utils/module_logger.py:get_module_logger` |
| 事件构造 | `app/business/agent/graph.py:chat_events` 四个 yield 点 |
| 事件落库 | `app/dao/event_log.py` + `app/business/dialog/message.py:persist_events` |
| 回放接口 | `app/api/chat.py: GET /chat/session/{id}/events` |
| 指标定义 / 端点 | `app/utils/metrics.py` + `app/api/app.py:/metrics` |

## 9. 后续演进（未本期）

- `node_latency_ms{node}` / `node_errors_total{node}` 需 LangGraph callback 埋点；`llm_tokens_total{model}` 需 `call_llm_async` 透出 `usage`。
- 跨服务分布式追踪：在图边界节点挂 OpenTelemetry span，把本方案 `trace_id` 作为 OTel `trace_id` 透传，接自托管 Jaeger；LangSmith 暂不引（隐私合规 + MVP 用不上）。
