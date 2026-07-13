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

## 7. 本项目参考结构

项目采用"确定性强的前置处理 + 一个策略节点做集中路由"的经典结构:

```
input_normalizer → intent_router → state_tracker → policy_layer →(条件)→
    clarification_node | agent_node | handoff_node | response_generator
    → context_compressor → END
```

优点:路由逻辑集中、好测。`policy_layer` 产出 `current_action`,由 `route_after_policy` 分发。
