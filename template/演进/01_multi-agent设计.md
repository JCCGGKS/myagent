# 01 MULTI-AGENT 设计（后续演进预案）

梳理「多工具调用」与「MULTI-AGENT 编排」两条演进线：现状已落地的多工具结果累积、暴露出的依赖工具一并执行问题、依赖治理方案全集，以及作为架构终局的 Orchestrator / MULTI-AGENT 设计。本文是**预案**，非待办——标注各方案的触发条件，按需启用。

## 1. 背景与动机

当前是单 Agent 架构：`CustomerServiceAgent`（`app/business/agent/graph.py`）一个 `agent_node` 调用全部 7 个工具（`query_order` / `query_logistics` / `rag_retrieve` / `request_refund` / `create_handoff` / `modify_address` / `apply_invoice`）。

演进来自两个真实诉求：

1. **多工具**：用户一次询问多个维度（如「查 A1001 的订单和物流」）需要一次发起多个独立工具调用，而非只调其中一个。
2. **依赖安全**：部分工具之间存在依赖关系，「一并输出并执行」会出错（详见 §3）。

两条线最终都收敛到 **MULTI-AGENT 编排**（§5）——按意图拆分专职子 Agent，由 Orchestrator 路由与排序，天然实现「意图作用域工具集」并彻底解决依赖问题。

## 2. 已落地：多工具结果累积（tool_result → tool_results）

**问题**：`ToolExecutor.run()` 每执行一个工具就把结果覆盖写入 `state.tool_result`（`last_result`），只有最后一个存活。ReAct 循环把 LLM 单条消息里的全部 `tool_calls` 一次性交给 `run()`，因此多工具请求最终只渲染了最后一个工具的结果，其余被静默丢弃。

**方案**（已提交 `0bf0dd4`，全量 `pytest` 149 passed）：

- `state.tool_result: ToolExecutionResult | None` → `state.tool_results: list[ToolExecutionResult]`（`app/schema/state.py`）。
- `run()` 去掉 `last_result`，改为 `state.tool_results.append(result)` 累积（重置由 `input_normalizer` 完成），多工具 + 多轮 ReAct 跨轮累加、互不覆盖。
- `create_handoff` 拆出 `_build_handoff_result`（不碰 `tool_results`），`create_handoff(state)` 与 `_handle_handoff` 各自 append，避免双重写入。
- `response_generator` 单结果保持原 `tool_response_templates` 逻辑；多结果聚合（非 RAG 按序拼接、RAG 文档走 LLM 综述）。
- SSE 每个工具结果发一条 `tool_result` 事件（前端单对象消费不变，一工具一 trace）；删除 `_serialize_tool_result`。
- 提示词遍历 `state.tool_results` 渲染「工具调用结果」+「严格遵循工具结果」约束。

**这一阶段只解决「结果不丢」，没解决「依赖工具不该一并执行」。** 详见 `评估调优/agent/06_工具调用.md` §7。

## 3. 核心问题：依赖工具一并执行

并行 function calling 的已知坑：`run()` 把一条消息里的全部 `tool_calls` 当作独立批执行，若其中某个工具的入参依赖另一个工具的输出，后者会在前者返回之前就跑，拿到空/旧数据。

**当前 7 工具实际无硬依赖**：每个工具都自己重新拉数据（如 `request_refund` 内部 `order_service.get_order_status(order_id)` 自查），没有任何工具去读另一个工具的 `tool_result`。所以「查订单和物流」能安全一并执行，因为它俩只依赖 `order_id`（来自 slots）。

**但「多工具」改造放大了风险**：为修「只调了物流」的 bug，我们在 `system.py` 的 agent 提示加了规则——

> 若用户一次询问订单的多个维度，请在同一次回复中发起**所有相关的独立工具调用**……

关键词是「独立」。模型不一定每次判得准：例如「把 A1001 物流所在城市设为收货地址」应「先 `query_logistics` 拿城市、再 `modify_address`」，一旦模型把这两个塞进同一条消息，`modify_address` 在 `query_logistics` 返回前就跑 → `new_address` 为空 → 校验报错，白费一轮（好在 ReAct 下轮能补救）。

**风险两类**：

1. **入参依赖前置输出**：后置工具的必填入参应取自前置工具的结果（如改地址依赖物流城市）。
2. **读后写竞态**：后置工具读前置工具的副作用结果，并行拿到旧值。

## 4. 依赖治理方案全集（A~N）

按「在哪一层拦截」分类。每条标注治的是**「模型一并输出」**还是**「执行器一并执行」**，并给代价与适配。

### 一、源头约束：不让模型把依赖工具塞进同一条消息

| 方案 | 说明 | 治理轴 | 代价 |
|---|---|---|---|
| **A. 提示词纪律** | 只并行「读类 + 互不依赖」调用，依赖的拆多轮 | 输出 | ≈0，靠 ReAct 多轮兜底 |
| **I. 模型自标依赖** | function call 带 `depends_on: [call_id]` 显式声明谁等谁 | 输出 | 比 A 可靠；**无需训练**，靠工具 JSON schema + 提示词让模型在推理时填字段（与 `request_refund.confirm` 字段同构），但依赖模型指令遵从，小模型/本地模型可能填不准 |
| **J. 彻底关掉并行** | 永远串行，一次只跑一个工具 | 输出+执行 | 过度修正，废掉「多维度一次出」的速度优势 |
| **K. 预审批白名单** | 人工维护「已知可并行」工具对，其余强制串行 | 执行 | 安全简单，但白名单随工具增长要维护，只防已知 |

### 二、执行器自动排序（靠元数据 / 推断）

| 方案 | 说明 | 治理轴 | 代价 |
|---|---|---|---|
| **B. Schema 声明 `depends_on` + 拓扑排序 + 输出注入** | 每工具声明依赖谁，`run()` 按序执行并把前置输出填进后置入参 | 执行 | 最稳、可验证；入参要做模板化，当前工具用不上 |
| **E. 启发式依赖探测** | 静态比对：必填参既不在 slots/已知入参、又匹配另一工具输出字段 → 推断依赖并串行 | 执行 | 零标注，但脆弱（字段名/语义对不上就漏判） |
| **F. 引用解析** | 入参可写 `$call_1.result.city` 引用同批其他结果，`run()` 排序并替换 | 执行 | 灵活；需定义引用语法 + 替换引擎 |

### 三、乐观执行 + 失败补救

| 方案 | 说明 | 治理轴 | 代价 |
|---|---|---|---|
| **G. 先并行跑、依赖失败的再补跑** | 批量乐观执行，缺前置数据报错的等前置回来后只重跑它 | 执行 | 独立调用仍并行（吞吐友好），但实现复杂、日志不干净 |
| **H. 批前落地性过滤** | 执行前逐个校验入参可解析，解析不了的先扣留，跑完可解析的、结果回灌后下轮补发 | 执行 | 把 ReAct「下一轮补」显式化，比 G 干净，但要改 `run()` 批逻辑 |

### 四、改调用范式

| 方案 | 说明 | 治理轴 | 代价 |
|---|---|---|---|
| **C. 读/写分层** | 批里出现任意副作用工具就先跑所有只读、再跑写类 | 执行 | 挡住最常见「读后写竞态」，比 B 轻；但只管竞态、不管真依赖 |
| **D. 先规划后执行** | 不让模型发并行调用，先产**有序步骤计划**（每步引用上一步输出），执行器按序跑、逐步喂结果 | 输出+执行 | 依赖交给我们可控的计划结构，最契合复杂多步；多一轮 LLM + 编排复杂度 |
| **L. 共享黑板** | 工具把输出写进 `state` 中间区，依赖工具从黑板读；配合序列化 | 执行 | 与 B 类似但更松耦合；状态更杂、要管生命周期 |

### 五、架构层

| 方案 | 说明 | 治理轴 | 代价 |
|---|---|---|---|
| **N. MULTI-AGENT Orchestrator** | 按意图拆子 Agent，由 Orchestrator 路由与排序（详见 §5） | 输出+执行 | 最彻底，但体量最大，等工具规模/依赖真正复杂再上 |

### 选型建议

- **当下**（7 工具无真依赖，问题只是「模型可能乱捆」）：**A 立即上**，成本≈0，配合 `tool_results` 累积足够稳。
- **出现真实依赖工具对**（如改地址要先用物流结果）：上 **B 或 I**（显式依赖声明）最稳，I 更轻、B 更可控。
- **想顺手挡未来读后写竞态**：**C** 作为轻量保险。

## 5. Orchestrator（MULTI-AGENT）设计

### 5.1 本质

把「一个 agent 调全部 7 工具」改成「**按意图拆子 Agent + 顶层编排**」。依赖排序是其天然副产品——编排层控制调用顺序，能先把 A 跑完、把结果喂给 B，而不是把 A、B 塞进同一条消息并行。

### 5.2 两种实现风格

**风格一：Router + 子图（scoped sub-agents）** — 最贴合现有 LangGraph + `agent_node`

- 保留 `intent_router` 出意图；把单个 `agent_node` 换成 `orchestrator_node`。
- 每个子 Agent = 现有 `AgentNodeService` + 一个**只挂自己工具**的 `ToolExecutor`（顺带解决 R4 意图作用域工具集）。
- 单意图 → 调对应子 Agent；跨意图/依赖 → 编排层按顺序调多个子 Agent，汇聚各自 `tool_result` 进 `state.tool_results`。

**风格二：Planner-then-Execute（显式计划 + 拓扑执行）** — 依赖控制最强

- `orchestrator_node` 先让 LLM 产一份**有序步骤计划** `{sub_agent, tool, args, depends_on}`；
- 按 `depends_on` 拓扑排序，**逐个**执行，每步结果写回 `state.tool_results` 并作为后续步上下文。

### 5.3 落点映射（对应现有文件）

| 改造点 | 现有 | Orchestrator 版 |
|---|---|---|
| 工具作用域 | `build_tool_schemas()` 全量下发 | 加 `scope=intent` 参数，子 Agent 只拿自己的工具（**顺解 R4**） |
| 单 Agent | `agent_node` + 全局 `ToolExecutor` | 多个子 Agent，各持 scoped `ToolExecutor` |
| 调度 | `policy_layer → agent_node` | `policy_layer → orchestrator_node`（顺序调子 Agent，汇聚 `tool_results`） |
| 依赖声明 | 无 | `TOOLS` 注册表加 `depends_on`，供拓扑排序 |

### 5.4 怎么根治依赖问题

关键在 `orchestrator_node` 的**顺序循环**而非 `run()` 的并行批：

```python
async def orchestrator_node(state):
    plan = plan_steps(state)            # 风格二；风格一只用 intent 决定子 Agent 列表
    topo = topo_sort(plan)              # 按 depends_on 排好先后
    for step in topo:
        sub = self.sub_agents[step.sub_agent]
        # 前置步的 tool_result 已进 state.tool_results，
        # 子 Agent 的 prompt 能直接看到 → 入参可从前置结果取
        await sub.run(state)            # 每个子 Agent 内部跑自己的 ReAct + tool_executor
        # sub.run 把结果 append 进 state.tool_results（复用已落地的累积）
    return state                        # tool_results 已汇聚，交 response_generator
```

依赖工具「改地址要用物流城市」：规划阶段把 `query_logistics` 排在 `modify_address` 之前，前者结果进 `state.tool_results`，后者子 Agent 的 prompt 能看到城市，`new_address` 不再为空。**不再有「一并执行」**。

### 5.5 顺带解决 R4（意图作用域工具集）

当前 `agent_node` 经 `build_tool_schemas()` 下发全量工具，误调风险工具面大。MULTI-AGENT 按意图拆子 Agent、各子 Agent 只持 scoped 工具，天然实现「意图作用域工具集」，无需在单 Agent 内做工具过滤。R1/R2/R5/R6 已对风险工具做足纵深防御，故本期（单 Agent）不做 R4 拆分，等 Orchestrator 一并落地。

### 5.6 代价 & 触发条件

- 最重：多一轮 LLM（规划）、子 Agent 生命周期管理、状态/上下文在子 Agent 间传递。
- 当前 7 工具无真依赖 → **暂不上**，A（提示词纪律）够用。
- 触发：工具规模膨胀到误调频发，或出现真实跨工具依赖（写依赖读的输出）。

## 6. 演进路线（分阶段）

| 阶段 | 内容 | 状态 |
|---|---|---|
| **阶段 0** | 多工具结果累积列表（tool_result → tool_results） | ✅ 已提交 `0bf0dd4` |
| **阶段 1（轻）** | A 提示词收敛（明确「只捆独立读类」）+ 预留 B 的 `depends_on` 接口位 | 待启动 |
| **阶段 2（中）** | 出现真依赖 → B/I 执行器侧硬方案；C 挡读后写竞态 | 按需 |
| **阶段 3（重）** | 工具规模/依赖复杂 → Orchestrator / MULTI-AGENT（风格一或二） | 按需 |

## 7. 开放问题（待决）

- 是否现在就在 `TOOLS` 注册表埋 `depends_on` 接口位（不实现，仅占位）？
- Orchestrator 用 LangGraph 编译子图（`StateGraph` subgraph + `Send` 动态 fan-out），还是命令式子 Agent（`orchestrator_node` 内循环调 `sub.run(state)`）？
- 多意图（`intent_result.extra_intents`）如何与子 Agent 编排联动——是按意图逐个派发子 Agent，还是由 Orchestrator 合并计划？
- `state.tool_results` 在子 Agent 间是共享同一份还是各自快照？跨子 Agent 的依赖读取是否需要带 trace 溯源？
