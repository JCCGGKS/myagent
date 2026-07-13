# 工具编排与观测（Tool Orchestration & Observability）

本文分五大块：**工具编排**（怎么把工具串起来）、**工具观测**（怎么看得清）、**工具健壮**（怎么不出错）、**多工具并行**（一轮调多个怎么编排）、**Orchestrator**（多 Agent 调度扩展）。

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

# 三、工具健壮（Tool Robustness）

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

> R1–R7 各项的**落地状态与代码落点**（二次确认、幂等、失败隔离、参数校验等）详见 `template/评估调优/agent/06_工具调用.md`，本文不重复展开。

---

# 四、多工具并行（Multi-tool Parallel）

多工具调用 = 一轮里要调多个工具才能回答（如「查订单状态 + 查物流 + 判断能否退款」）。本质是**把多个 `tool_result` 聚合成一个答案**，难点不在「调」而在「编排与整合」。

## 1. 编排模式
- **并行（independent）**：工具间无依赖 → 一次 LLM 输出多个 `tool_calls`，并发执行，省延迟（如同时查订单和物流）。
- **串行（dependent）**：后一个入参依赖前一个出参 → 必须等前者返回再发下一次（如先查订单拿 order_id，再查物流）。
- **依赖 DAG**：多工具构成有向图，按拓扑序执行，同一层可并行。
- **动态（LLM 驱动）**：每轮根据上轮结果决定下一个工具，直到信息齐了再作答（ReAct 式，本项目 `agent_node` 即此）。

## 2. 原生多工具输出：`tool_calls` 是数组
API Function Calling 原生支持一次返回多个工具调用——`message.tool_calls` 是**数组**（parallel function calling）。但要分清：
1. **API 能输出多个** ✅ —— `ToolExecutor` 遍历列表天然承载多工具。
2. **API 不表达依赖关系** ⚠️ —— 只把多个调用打包返回，**不标谁依赖谁、也不保证顺序有意义**。真·独立才并发（`asyncio.gather`），有依赖得自己串行化（跑完上游、结果喂回、再开下一轮）。
3. 并非所有模型都支持并行 tool calls，部分一次只吐一个。

## 3. 典型问题与处理
| 问题 | 处理 |
|---|---|
| 依赖顺序错（没拿到上游就调下游） | 串行化；下游入参缺失直接判 dependent，不并行 |
| 部分失败（N 个里 K 个挂） | 成功的照常聚合；失败的下发 `tool_result{ok=false}`，让 LLM 决定重试/问用户/转人工；不因 1 个失败丢其余结果 |
| 结果冲突（订单说已发、物流说未揽收） | 冲突如实呈现 + 建议转人工，不自作主张选一个 |
| 结果过多/无关 | 只把回答需要的字段喂 LLM（截断/抽取），避免 prompt 膨胀 |
| 调用爆炸（LLM 无限开工具） | 设最大并发 + 最大总调用次数，超限强制进 `response_generator` |
| 延迟堆叠 | 独立工具强制并行；慢工具设超时；可缓存的加缓存 |

## 4. 兜底
- **依赖链断**：上游失败 → 下游短路不再执行，直接转「缺信息 / 转人工」。
- **全失败**：所有工具都 `ok=false` → 降级转人工（优雅降级，不是空答）。
- **聚合失败**：工具都成功但 LLM 整合不出 → 退回逐条展示原始结果 + 转人工。

## 5. 并行调度设计（落地）
核心思路：同一轮内的多个 `tool_calls` 之间没有数据依赖，用并发原语同时执行，收集全部结果后再回灌。

- **线程池（同步接口，改动最小）**：把 `ToolExecutor.run` 的循环改成 `ThreadPoolExecutor` 并发 `map`（`query_order` 查库、`query_logistics` 调外部 API、`rag_retrieve` 向量检索都是 I/O 密集型，并发能显著压低总延迟）。`ToolExecutor.run` 现状为**串行**循环（`tool_executor.py:167`）：

  ```python
  for tc in tool_calls:
      result = self._execute_one(name, args, state)   # 逐个执行
      tool_messages.append(...)
  ```

- **异步（asyncio，配合异步工具客户端）**：若工具客户端本身是 `awaitable`（如 `httpx.AsyncClient`、`asyncpg`），用 `asyncio.gather` 并发——延迟最优，但要求工具层全部异步化（本仓库当前是同步 `OrderService`/`LogisticsService`，需改造）。

## 6. 依赖感知的「并行 + 串行」调度
更真实的多轮场景里，工具之间存在依赖（B 需要 A 的结果）。调度策略：

1. 第一轮：模型给出无依赖的多个 `tool_calls` → 全部并行执行；
2. 结果回灌后，模型基于观察再决定下一轮（可能又是一组可并行的 `tool_calls`）；
3. 如此逐轮推进，轮内并行、轮间串行——正是 `AgentNodeService` 的 `for _round` 循环 + 轮内并发的组合。

> 关键约束：**只有同一轮内的 `tool_calls` 可安全并行**。跨轮必须串行，因为后一轮的推理依赖前一轮的观察。

## 7. 注意事项
- **结果顺序**：`tool_calls` 与 `role: "tool"` 消息靠 `tool_call_id` 一一对应，并行后仍需按 `tool_call_id` 回填，不能只靠列表顺序。
- **失败隔离**：单个工具超时/报错不应阻塞同轮其他工具——用 `try/except` 包裹每个 `_execute_one`，错误也作为 `tool` 消息回灌，让模型自己决定降级。
- **限流**：并发调用外部 API 要加信号量/`max_workers`，避免打爆下游。
- **幂等**：并行工具最好是只读/幂等的（`query_order`/`query_logistics`/`rag_retrieve` 都是）；带副作用的工具（如 `create_handoff`）应**禁止并行**，且最好单轮只调一次（见 三、风险工具）。
- **最大轮次**：保留 `max_tool_rounds`（本仓库=3）防止无限循环。

## 8. 落地优先级
1. 先把 `ToolExecutor.run` 的串行循环换成线程池并发（低风险、立竿见影）；
2. 给 `create_handoff` 等副作用工具加「单轮去重 / 禁用并行」标记；
3. 工具层异步化后，再升级到 `asyncio.gather` 方案。

## 9. 与项目落点的对应
- `ToolExecutor` 已支持一次执行多个 `tool_calls`（遍历列表），可承载并行/串行混合；当前 `agent_node` 是**动态串行**（ReAct 式逐轮），要真并行需把独立调用改 `asyncio.gather` 并发。
- 每个 `tool_result` 已是结构化 `{name, args, ok, error, latency}`，多工具时逐个落 `event_log`，`trace_id` 串起整批。
- 并行时更要防「风险工具被并行触发」——确认/闸门逻辑须对每个调用独立生效（见 三、风险工具）。

---

# 五、Orchestrator

## 1. 多 Agent 编排（Orchestrator + Workers）

一个调度 agent 把子任务派给专精 agent，各自有自己的工具集。

- 控制流：层级/对等协作
- 优点：关注点分离，单 agent prompt 不膨胀，可独立迭代
- 缺点：token 成本高、上下文传递易丢、编排 agent 是瓶颈
- 适用：跨领域、复杂长任务

选型维度见 一、工具编排的「选型关键维度」：任务跨度窄 → 单 agent；宽 → 多 agent。

## 拓展知识

**Orchestrator 是什么**：在 Multi-Agent 架构里，Orchestrator（编排器/调度者）是顶层「总指挥」——它**不直接干活**，而是负责「理解任务 → 拆解/路由 → 派发给专职 Worker 子 Agent → 汇总结果」。配套的 Workers 是各管一摊的专职 Agent（如订单 Agent / 退款 Agent / 物流 Agent）。类比：Orchestrator 是工头，Worker 是各工种师傅。

**本项目目前用到了吗**：

- **没有用真正的 Multi-Agent Orchestrator**。代码全库 grep，"orchestrator" 一词**只出现在文档**（`tool编排.md`、`tool_calling.md`、`06_工具调用.md`）与 `graph.py` 一句泛化报错文案（`LangGraph is required for agent orchestration`），**无任何 Orchestrator 类**。
- 现在实际是 **单 Agent + 节点流水线**：`CustomerServiceAgent`（`graph.py`）用 LangGraph `StateGraph` 编排 `input_normalizer → intent_router → state_tracker → policy_layer →（条件分支）→ clarification / agent_node / handoff_node → response_generator → context_compressor`；`agent_node` 是**一个 ReAct 循环、握着全部 7 个工具**。这是「单 Agent」，不是「Orchestrator + Workers」。
- **路由雏形已在单 Agent 内**：`policy_layer` → `route_after_policy` 按 `current_action` 分流到澄清/agent/转人工节点；`intent_router` 识别意图。但它们路由到**同一 Agent 内的节点**，不是派发给外部 Worker Agent。

**何时引入（与 R4 的关系）**：

- 当前工具少（7 个），按意图裁剪收益低，且有 R1–R6 兜底，故 R4 暂缓、不在单 Agent 内做工具过滤（见 三、风险工具 §4.1）。
- 后续工具规模变大、误调/延迟明显时，升级为 **MULTIAGENT**：顶层 Orchestrator 按意图把请求派发给专职 Worker Agent，每个 Worker 只持自己领域的工具——**R4（意图作用域工具集）随之天然落地**，且 prompt/策略按意图隔离、职责更清晰。
- 一句话总结：**现在只有「单 Agent 内的节点路由」，没有跨 Agent 的 Orchestrator；Orchestrator 是规划好的后续扩展方向，也是 R4 的归宿。**
