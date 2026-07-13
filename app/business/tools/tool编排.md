# 工具编排与观测（Tool Orchestration & Observability）

本文分两大块：**工具编排**（怎么把工具串起来）与 **观测**（怎么把它看得清）。

---

# 一、工具编排（Tool Orchestration）

工具编排核心解决一个问题：**让 LLM 在合适时机调用合适的工具，并把结果正确接回推理链**。脱离具体框架，主流范式其实就几类，区别主要在「谁来决策下一步」和「控制流有多灵活」。

## 1. 单循环 Function Calling（ReAct）

LLM 自己决定「调哪个工具 → 看结果 → 再调/回答」。

- 控制流：隐式，完全由模型驱动
- 优点：实现简单，泛化强，适合开放式任务
- 缺点：不可控（可能死循环/乱跳）、难加业务约束、调试靠运气
- 适用：探索型、单次任务、对确定性要求不高

## 2. 硬编码 DAG / 状态图（LangGraph 模式）

把流程显式画成图，节点是确定逻辑，只有少数节点（agent_node）才让 LLM 发挥。

- 控制流：显式图 + 条件分支
- 优点：可预测、可审计、易插业务规则、出错易定位
- 缺点：图写死，灵活任务要改代码；跨图复用难
- 适用：流程相对固定（客服、工单、审批）

## 3. Planner-Executor（先规划后执行）

先让 LLM 产出完整 plan（工具调用序列），再确定性执行。

- 控制流：规划与执行分离
- 优点：plan 可人工确认、可回放、可并行调度
- 缺点：plan 一旦错误，执行越走越偏；长任务中途变化难修正
- 适用：多步、可分解、需要人工把关的任务

## 4. 多 Agent 编排（Orchestrator + Workers）

一个调度 agent 把子任务派给专精 agent，各自有自己的工具集。

- 控制流：层级/对等协作
- 优点：关注点分离，单 agent prompt 不膨胀，可独立迭代
- 缺点：token 成本高、上下文传递易丢、编排 agent 是瓶颈
- 适用：跨领域、复杂长任务

## 选型关键维度

| 维度 | 偏哪边选什么 |
|---|---|
| 流程确定性 | 高 → DAG/状态图；低 → 单循环 |
| 是否需要审计/合规 | 高 → 显式图 + 落库快照 |
| 任务跨度 | 窄 → 单 agent；宽 → 多 agent |
| 容错要求 | 高 → planner 先确认 |
| 迭代成本 | 图易改 → DAG；想少写代码 → function calling |

## 常被忽略的点：编排 ≠ 调度

多数"工具编排"真正难的是三件事，不是"调工具"本身：

1. **槽位/状态管理**：多轮对话里哪些信息已齐、还缺什么
2. **边界**：LLM 输出何时转成确定性动作（落库、发消息），避免"模型说了算"导致的副作用
3. **可观测**：每一步的 intent/state/tool_result 都要能 trace，否则线上无法排障

## 核心原则

把"确定性"和"智能性"的分界线画清楚——能用规则/图走的绝不交给 LLM 决策，只在真正需要理解语义的节点（意图识别、生成话术）才放模型。

---

# 二、观测（Observability）

观测在工具编排里不是「加个日志」就完事，它贯穿 **trace（链路）→ state（状态）→ action（动作）→ result（结果）** 四层。核心目标只有一个：**线上出问题，能还原「那一轮 LLM 为什么这么决策、调了什么、结果怎样」**。

本项目落地的是**三层协作**的自托管方案（无外部 SaaS、无 LangSmith，契合客服数据合规）：

## 1. 三层模型与分工

| 层 | 本质 | 职责 | 本项目落点 |
|---|---|---|---|
| **Logs** | 系统级 catch-all | 计划外异常 / 兜底降级 / 启动生命周期 | 单文件 `logs/app-*.log`，每行 `[tid=...] [tag] ...` |
| **event_log** | 单请求链路追踪（trace） | 这一轮「为什么这么答」的决策链回放 | `event_log` 表 + `GET /chat/session/{id}/events?trace_id=` |
| **Metrics** | 跨请求聚合/告警 | 调用量 / 延迟 / 失败率 / 意图分布 | `/metrics` 端点（Prometheus + Grafana） |

**`trace_id` 是三层的 pivot**：任一层的记录都带 `trace_id`，互相串联。排障路径：
`日志` 发现 `persist_failed` → 拿 `tid` → `event_log` 回放该轮决策链 → 定位哪步出错。

## 2. 本项目的落地要点

### 2.1 event_log = 单请求链路追踪
`event_log` 本质就是**自托管的单请求 trace（span）层**：每条记录是决策链上的一个节点，靠 `trace_id` 串成完整链路，可回放「这一轮为什么这么答」。对应 OTel 的 span 概念，但我们没引入 OTel SDK/Jaeger，数据不出本机。

- 表结构：`id / session_id / trace_id / turn / event_type / node / payload / created_at`
- 事件类型（节点埋点）：`intent → state → tool_result → final`（异常时 `error`）
- 节点记录清单：
  - `intent_router`：`intent` 事件（main/sub/confidence/slots/needs_clarification）
  - `state_tracker` / `policy_layer`：`state` 事件 + `current_action` 路由决策依据
  - `agent_node`：`tool_result` 事件（name/args/ok/error/latency）
  - `response_generator`：`final` 事件（终态回复 + 状态快照）
  - 图跑完由 `MessageService.persist_events` **best-effort** 批量落库（失败仅记日志，绝不阻断 `final` 下发）
- 回放：`GET /chat/session/{session_id}/events?trace_id=`（复用 `session_service.get_owner` 鉴权，防越权读他人会话）

### 2.2 Logs：单文件 + `[tid]` + `[tag]`
- **单一日志系统、单一文件**：所有模块共用 `logging.getLogger("myagent")`，`propagate=True` 落 `logs/app-YYYY-MM-DD.log`（按天滚动）。不按模块拆文件——单条请求跨多模块，拆开会打散无法还原。
- **每行带 `trace_id`**：`contextvars.ContextVar` + `logging.Filter`（`TraceIdFilter`）注入 `[tid=...]`，无请求上下文记 `-`；`trace_id` 由 `TraceIdMiddleware` 在请求入口分配（可沿用上游 `X-Trace-Id`）。
- **`[tag]` 分段检索**：`[api]`/`[auth]`/`[rag]`（接口层）、`[intent]`/`[tool]`/`[state]`/`[policy]`/`[agent]`/`[handoff]`/`[response]`/`[compressor]`/`[persist]`/`[infra]`（pipeline）。grep `tid=xxx` 还原单次请求，grep `[tool]` 只看工具调用。

### 2.3 Metrics：聚合与告警
- `app/utils/metrics.py` 定义低基数指标（label 只用 `intent`/`tool_name`/`node`/`status`/`model`，**绝不**放 `user_id`/`session_id`/prompt，避免基数爆炸）：
  `myagent_requests_total` / `myagent_request_latency_seconds` / `myagent_tool_calls_total` / `myagent_tool_latency_seconds` / `myagent_handoff_total` / `myagent_low_confidence_total`
- `GET /metrics` 端点（已放行鉴权），`docker-compose` 加 prometheus + grafana 抓取。

## 3. 关键原则 / 踩坑

- **event_log 不能替代日志**：事件流只记规划好的节点；Redis 初始化失败、LLM 超时、落库失败（`persist_failed`）、启动/健康检查等计划外异常只进日志——而且落库自身失败时 event_log 里根本不会有这条，日志是兜底最后一道。
- **不要记全量 prompt 到 production 日志**（隐私/成本），记 hash 或截断 + 落库隔离。
- **LLM 失败要有降级 trace**：兜底路径（如 `LLMIntentFallbackService`）必须可见，否则"为什么答非所问"查不出来。
- **结构化优先于文本**：用 JSON/span（event_log），别用自由文本 `print`，后面没法聚合查询。
- **异常也要可观测**：`error` 事件不仅给前端，要带 `trace_id` + 节点名 + 入参，否则线上报错等于没报。
- **工具调用的"三要素"必须全**：入参（原始+解析后）、出参或错误（区分超时/异常/业务失败）、耗时+重试——由统一 `ToolExecutor` 包装层做，业务工具不各自打点。

## 4. 一句话总结

可观测的本质是：**让 LLM 的"黑盒决策"变成一串可记录、可回放、可查询的事件流**。本项目用 `trace_id` 把三层（logs 旁注 + event_log 决策链 + metrics 聚合）串成一条完整链路——`trace_id` 是枢纽，event_log 是单请求 trace，logs 是同源非结构化旁注，metrics 是跨请求聚合。

---

# 三、工具调用的健壮性（Robustness）

工具调用链路按阶段出问题，处理方式完全不同。

## 1. 问题分类（按链路阶段）

- **选型**：调了不该调的工具 / 幻觉不存在的工具
- **入参**：槽位缺失 / 格式错 / `arguments` 非法 JSON
- **执行**：依赖挂、超时、限流、业务失败（订单不存在 / 不满足退款）
- **用结果**：LLM 忽略 `tool_result` 幻觉、漏读关键字段
- **控制流**：死循环、破坏性副作用由模型独断

## 2. 处理（每类应对）

| 阶段 | 手段 |
|---|---|
| 选型 | 意图先路由再放行工具；按意图收敛工具集；未知意图走 `unsupported.unknown` |
| 入参 | schema 校验；不过回灌 LLM 重抽（N 次）；缺槽位 → `missing_slots` 澄清 |
| 执行 | `ToolExecutor` 统一 `try/except` 产 `tool_result{ok,error_type,latency}`；超时设上限；可重试带退避 |
| 用结果 | prompt 约束「严格依据 `tool_result`」；喂原始结果；业务失败明确类型 |
| 控制流 | 最大轮次/调用次数；循环检测；超限强制 `response_generator`；破坏性动作两步确认或 policy 闸门 |

## 3. 兜底（分级）

1. **参数级**：校验失败 → 回灌修正（N 次）→ 仍失败 → 澄清要缺的槽位
2. **工具级**：`ok=false` → LLM 决定重试/问用户/转人工；依赖挂 → 优先转人工
3. **意图级**：function-calling 异常 → `LLMIntentFallbackService` 兜底解析
4. **链路级**：整条跑崩 → 捕获异常发 `error` 事件（带 `tid`+节点+入参）→ 安抚话术/转人工，不甩 500
5. **全局**：LLM/依赖全挂 → canned response + 转人工，best-effort 保证有回应

原则：任一层失败都向下一层兜底，全程带 `trace_id` 留痕。

## 4. 风险工具专门处理

风险工具 = 带不可逆副作用/外部后果（`request_refund` 动钱、`request_human` 拉真人），与普通只读工具分开处理：

- **读/写分离**：`consult_policy`（只读）与 `request_refund`（写）拆子意图
- **二次确认**：执行前需 `confirmed_slots` 显式确认，否则发确认话术不执行
- **policy 闸门**：执行由 `policy_layer`/状态机放行，LLM 只建议不独断
- **强审计**：必进 `event_log` + 日志 `[tid]`，最好独立审计表，可对账
- **幂等**：退款同订单+金额+请求号不重复扣，重试/循环不二次退款
- **最小权限 + 限额**：默认只读，写带上限，超额升级人工
- **防循环误触发**：一旦触发进终态，避免重复调用
- **兜底指向「人」**：误触发优先转人工 + 留痕 + 对账，不自动重试破坏性动作
