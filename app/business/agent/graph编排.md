# Graph 节点编排(通用范式)

> 抛开具体项目,从 LangGraph 通用范式梳理 graph 节点编排的核心思路。

## 1. State 是骨架,不是附属品

整个图共享一个 state 对象(通常是 typed dict 或 pydantic model)。编排的本质是**定义节点如何读写 state,以及沿什么路径流转**。

关键点:state 字段要区分两种更新语义:

- **覆盖型**(如 `current_intent`):后写覆盖前写
- **累积型**(如 `messages` / `action_history`):用 reducer 合并(append),否则多轮会丢上下文

```python
from typing import Annotated, TypedDict

def _append(left, right):
    return left + right

class State(TypedDict):
    messages: Annotated[list, _append]   # reducer 累积
    intent: str                          # 直接覆盖
```

## 2. 节点的单一职责

每个节点就做一件事,返回一段 state patch(dict),框架负责合并:

```python
def intent_router(state) -> dict:
    intent = classify(state["messages"])
    return {"intent": intent, "confidence": intent.score}

def agent_node(state) -> dict:
    result = call_tools(state["messages"])
    return {"messages": [result]}   # 累积进 messages
```

节点应该**无副作用落库**——持久化、发消息这种 IO 放到图外统一处理(参考 `MessageService.persist` 模式)。

## 3. 三种边(edge)

- **普通边**:`graph.add_edge("a", "b")`,固定顺序
- **条件边**:`graph.add_conditional_edges("policy", route_fn, {"clarify": "clarify_node", "act": "agent_node"})`——`route_fn` 读 state 决定下一个节点
- **入口/终点**:`set_entry_point` / `set_finish_point`,或节点返回 `END`

编排的灵活性 90% 来自条件边。

## 4. 四种常见拓扑

```
线性:   input → router → tracker → response → END
分支:   policy ─┬→ clarify
                ├→ agent
                └→ handoff
循环:   agent → (缺槽?) → clarify → agent   # 用条件边指回自己
扇出:   router → fan_out 并行查多个工具 → 聚合节点(需手动 Join)
```

循环最容易出错:必须有一个收敛条件,否则死循环。通常靠 `stage` / `missing_slots` 为空的判断退出。

## 5. 持久化 / 断点续跑

LangGraph 的持久化本质是把 **state 快照(checkpoint)** 按 `thread_id`(会话)落盘,崩溃 / 续跑 / 人工介入都靠它。

### 5.1 官方 Checkpointer 方案

| 方案 | 类 | 适用 | 备注 |
|---|---|---|---|
| 内存 | `MemorySaver` / `InMemorySaver` | 本地开发、单测 | 进程退出即丢;**多 worker 不共享** |
| SQLite | `SqliteSaver` / `AsyncSqliteSaver` | 单机本地部署 | 文件级锁,单节点够用 |
| Postgres | `PostgresSaver` / `AsyncPostgresSaver` | 生产 | 需 `psycopg`(async 用 `psycopg[v])`;支持多 worker 共享 |
| Redis | `AsyncRedisSaver`(独立包 `langgraph-checkpoint-redis`) | 生产 / 高并发 | 内存型,快;需自管持久化(AOF/RDB) |

> 这些分属不同包——`langgraph-checkpoint`(核心抽象)、`langgraph-checkpoint-sqlite`、`langgraph-checkpoint-postgres`、`langgraph-checkpoint-redis`。核心接口都是 `BaseCheckpointSaver`。

### 5.2 用法骨架

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async with AsyncPostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
    graph = builder.compile(checkpointer=checkpointer)
    # 同 thread_id 自动从最后一个成功 checkpoint 续跑
    await graph.ainvoke(input, config={"configurable": {"thread_id": "u-001"}})
```

崩溃恢复是自动的:图从最后一个成功 checkpoint 继续,不会重跑已完成的节点。

### 5.3 两个容易混的概念

- **Checkpointer(短期 / 单线程记忆)**:按 `thread_id` 存每步 state 快照,支撑断点续跑 + `interrupt_before` 人工介入。
- **Store(长期 / 跨线程记忆)**:`BaseStore`(`InMemoryStore` / `PostgresStore`),按 `userId` / `namespace` 存跨会话长期知识(用户画像、偏好),不随会话结束清空(对应项目 `app/business/memory/` 占位)。

### 5.4 多 worker 部署注意点

- `MemorySaver` 是每个 worker 进程一份内存,多 worker 之间 state 不互通 → SSE 续跑 / 人工介入会错乱。
- 多 worker(`uvicorn --workers N`)必须上 **Postgres / Redis** 等共享存储,才能按 `thread_id` 正确路由到同一份会话状态。
- checkpoint 存的是**完整 state 快照**(非 diff),`messages` 这类累积字段越存越大。高频长会话建议:用 context compressor(项目已有 `context_compressor`)在落库前压 `running_summary`;或把大字段拆到外部存储,state 只留指针。

## 6. 编排决策 checklist

设计一张图时,按此顺序思考:

1. **state 里哪些字段是累积、哪些是覆盖?**(先定 reducer)
2. **哪些节点是确定性逻辑、哪些必须调 LLM?**(确定性逻辑尽量不进 LLM,省钱省时)
3. **分支点依据哪几个 state 字段判断?**(条件边的函数要尽量读单点状态)
4. **循环怎么收敛?**(明确退出条件)
5. **副作用(写库/发消息)放哪?** 图内只产出,图外统一落库
6. **需要断点续跑 / 人工介入吗?** 决定要不要接 checkpointer + interrupt

## 7. 本项目实际编排(graph.py)

项目采用"确定性强的前置处理 + 集中路由"结构,且**在意图路由之前插入一个确定性 guard**
(`confirmation_guard`)处理退款二次确认,避免把确认信号交给 LLM 自由函数调用而丢失上下文。

### 7.1 节点与边(完整)

```
START → input_normalizer → confirmation_guard → intent_router → state_tracker → policy_layer
```

`policy_layer` 之后有 4 条出边,最终都汇入 `context_compressor → END`(澄清分支跳过 `response_generator`,其余三条先经 `response_generator` 成型回复):

```
澄清分支:  policy_layer → clarification_node ───────────────→ context_compressor → END
工具分支:  policy_layer → agent_node     ──→ response_generator ─→ context_compressor → END
转人分支:  policy_layer → handoff_node  ──→ response_generator ─→ context_compressor → END
直达分支:  policy_layer → response_generator ───────────────→ context_compressor → END
```

| 边 | 类型 | 路由依据 |
|---|---|---|
| `START → input_normalizer` | 普通 | — |
| `input_normalizer → confirmation_guard` | 普通 | — |
| `confirmation_guard → intent_router` | 条件(`route_after_confirmation_guard`) | `normal`(无挂起确认 / 已清挂起) |
| `confirmation_guard → response_generator` | 条件 | `handled`(`state.reply` 或 `state.tool_result` 已设置) |
| `intent_router → state_tracker` | 普通 | — |
| `state_tracker → policy_layer` | 普通 | — |
| `policy_layer → clarification_node` | 条件(`route_after_policy`) | `current_action ∈ {ask_intent_clarification, ask_slot_clarification}` |
| `policy_layer → agent_node` | 条件 | `current_action == agent_process` |
| `policy_layer → handoff_node` | 条件 | `current_action == handoff_human` |
| `policy_layer → response_generator` | 条件 | 其它(如 `answer_directly`) |
| `clarification_node → context_compressor` | 普通 | —(注意:澄清分支**不经过** `response_generator`) |
| `agent_node → response_generator` | 普通 | — |
| `handoff_node → response_generator` | 普通 | — |
| `response_generator → context_compressor` | 普通 | — |
| `context_compressor → END` | 普通 | — |

> 图态载体是 `dict`:`{"state": ConversationState, "request": ChatRequest}`;`state` 才是真正的
> 业务状态(见 7.3)。`thread_id = session_id`,checkpointer 按它续跑。

### 7.2 各节点职责

| 节点 | 职责 | 关键写入 |
|---|---|---|
| `input_normalizer` | 每轮重置 `reply`/`intent_result`/`tool_result`/`handoff`/`handoff_reason`/`current_action`,写 `channel`,把用户消息追加到 `recent_messages` | `recent_messages` |
| `confirmation_guard` | R1 二次确认确定性拦截。无 `pending_confirmation` 则放行;有则用 `classify_confirm_signal` 判确认/取消/转话题。`cancel`→设取消话术;`confirm`→以 `confirm=true` 重放工具(绕过 LLM);转话题→清挂起态 | `reply` / `tool_result` / `pending_confirmation` |
| `intent_router` | 调 `IntentRouterService.route` 识别 main/sub/confidence/slots/needs_clarification | `intent_result` |
| `state_tracker` | `StateTrackerService.apply` 合并槽位、推进 `stage`、算 `missing_slots` | `slots` / `missing_slots` / `stage` / `current_main_intent` 等 |
| `policy_layer` | `HandoffClarificationPolicy.decide` 产出 `current_action` | `current_action` |
| `clarification_node` | `ClarificationService.generate` 产出追问/澄清话术 | `reply` / `needs_clarification` |
| `agent_node` | `AgentNodeService.run` 走 LLM function-calling 调业务工具 | `tool_results` / `pending_confirmation`(退款确认) |
| `handoff_node` | `tool_executor.create_handoff` 构造转人工负载 | `handoff=True` / `handoff_reason` |
| `response_generator` | `ResponseService.generate` —— **`state.reply` 唯一写入方**。已设 `reply` 则早返回;否则按 `tool_results` 模板或 LLM 生成 | `reply` / `action_history` |
| `context_compressor` | `ContextService.compress` 维护 `recent_messages` 窗口 + `running_summary`,防快照膨胀 | `recent_messages` / `running_summary` / `summary` |

### 7.3 状态字段(ConversationState,`app/schema/state.py`)

| 字段 | 类型 | 默认值 | 当前取值 |
|---|---|---|---|
| `session_id` | str | (必填) | 任意字符串,**全局唯一**,作为 `thread_id` |
| `user_id` | int | (必填) | 归属用户 ID |
| `channel` | str | (必填) | 接入渠道,如 `web` |
| `recent_messages` | list[dict] | `[]` | `[{role, content}, ...]`,被 `context_compressor` 维护窗口 |
| `summary` | str | `""` | 会话摘要文本 |
| `running_summary` | str | `""` | 滚动压缩摘要文本 |
| `current_main_intent` | MainIntentCode | `"unrecognize"` | `order_query` / `logistics` / `after_sale_refund` / `complaint` / `handoff_service` / `unrecognize` / `unsupported_biz` |
| `current_sub_intent` | SubIntentCode | `"unrecognize.unknown"` | `order_query.query_status` `order_query.modify_address` `order_query.apply_invoice` `logistics.lost_package` `logistics.delayed` `logistics.not_received` `after_sale_refund.request_refund` `after_sale_refund.consult_policy` `after_sale_refund.damage_refund` `after_sale_refund.no_reason_return` `after_sale_refund.wrong_goods` `complaint.compensate` `complaint.service_complaint` `handoff_service.request_human` `unrecognize.unknown` `unsupported_biz.out_of_scope` |
| `stage` | str | `"new"` | `new` / `collecting_info` / `executing` / `responding` / `handoff` / `unsupported` |
| `slots` | dict[str, str] | `{}` | 已抽取槽位,如 `{order_id: "A1001"}` |
| `missing_slots` | list[str] | `[]` | 待补槽位名列表 |
| `confirmed_slots` | list[str] | `[]` | 已确认槽位名列表 |
| `emotion` | EmotionState | `primary="neutral"` | `primary`: `neutral` / `positive` / `negative` |
| `needs_clarification` | bool | `False` | `True` / `False` |
| `intent_clarification_count` | int | `0` | 非负整数(澄清轮次计数) |
| `current_action` | str | `""` | `""` / `ask_intent_clarification` / `ask_slot_clarification` / `agent_process` / `handoff_human` / `answer_directly`(条件边据此分发;`""` 与 `answer_directly` 均走 `response_generator`) |
| `action_history` | list[ActionRecord] | `[]` | `[{action_name, status, summary, created_at}, ...]` |
| `intent_result` | IntentResult \| None | `None` | 本轮回意识别结果,或 `None` |
| `tool_results` | list[ToolExecutionResult] | `[]` | 每项 `kind`: `success` / `error` / `confirmation` / `handoff`(模板回复用) |
| `handoff` | bool | `False` | `True` / `False`(是否转人工) |
| `handoff_reason` | str | `""` | 转人工原因文本 |
| `pending_confirmation` | dict \| None | `None` | R1 二次确认挂起负载,如 `{tool, order_id, refund_type, reason}`,或 `None` |
| `reply` | str | `""` | 本轮助手回复文本(`response_generator` 为唯一写入方) |

> ⚠️ **字段一致性提示**:`graph.py` 多处引用 `state.tool_result`(**单数**),但 `ConversationState`
> 声明的字段是 `tool_results`(**复数**)。单数 `tool_result` 不是 pydantic 声明字段,checkpoint
> 序列化(`model_dump`)不会包含它,跨轮/落库可能丢失。建议全量统一为 `tool_results`。

### 7.4 编排要点回顾

- 两处分叉:`confirmation_guard`(确定性、零 LLM 成本、防 R1 回归)在前;`policy_layer`(集中路由)在后。
- 路由逻辑集中、好测:`policy_layer` 产出 `current_action`,由 `route_after_policy` 单点分发。
- 图内只产出、图外统一落库:`chat()` / `chat_events()` 跑完图后由 `MessageService.persist` 落库,
  `final` 事件在落库之后才下发。
- checkpointer(`MemorySaver` / `AsyncRedisSaver`)按 `session_id` 续跑;Redis 路径带 TTL,删会话时清 key。
