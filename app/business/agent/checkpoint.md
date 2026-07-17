# LangGraph Checkpoint 详解（结合本项目）

> 定位：本仓库用 `StateGraph(dict)` 编排客服 Agent（见 `graph.py`）。本文把 LangGraph 的
> checkpoint 机制讲清楚，并给出「是否 / 如何」接入本项目的落地建议。结论先行：
> **当前手写方案（MessageService + DAO）对 MVP 够用；checkpointer 是「图态 continuity +
> 暂停恢复（interrupt）+ 重放调试」的原语，引入需另挂一套存储（推荐 Redis）。**

---

## 1. 什么是 Checkpoint

Checkpointer 是 LangGraph 的**图状态持久化层**。它把每一轮图执行结束后的状态
（你 `StateGraph` 的状态类型，本仓库是 `dict`，即 `ConversationState` 那套字段）按
**`thread_id`** 存起来，使多轮对话可以「续跑」、可以「重放」、可以「从某一步分叉」。

关键概念：

- **`thread_id`**：对话线程标识。同一个 `thread_id` 的多次 `ainvoke` 共享同一份历史状态。
- **`checkpoint_id`**：每一步落盘快照的唯一 ID，用于时间旅行（指定从哪一步恢复）。
- **`checkpoint_ns`**：命名空间，子图 / 多分支场景下隔离状态用。
- **step**：一个「节点执行单元」。图每跑完一个节点，checkpointer 自动写一份快照。

数据形态：checkpointer 存的是**序列化的图状态 dict**，不是给人看的消息流。

---

## 2. 本项目现状（为什么现在没用）

搜 `app/` 全量：**代码里没有任何 checkpointer 配置**（`MemorySaver` / `*Saver` 均无引用）。
文档 `app/business/README.md:43` 与 `app/business/dialog/README.md:34` 提到图
「可被 checkpointer 重放」，那是**设计意图**，不是现状。

当前跨轮状态是**手写**的：

1. 图运行期间只读内存态 `ConversationState`，不碰存储；
2. 图跑完，`chat()` / `chat_events` 调 `MessageService.persist` 把
   「用户消息 + 助手回复 + 状态快照」批量写进 MySQL（或内存 DAO）；
3. 下一轮从 DB 读回历史、重建 `ConversationState`，再喂给图。

那套 `slots` 跨轮继承机制，正是在「没有 checkpointer」
前提下自己实现的跨轮状态管理。

---

## 3. 落盘落到哪里（backend 对比）

checkpointer 落到哪完全由 `compile(checkpointer=...)` 时传入的实现决定：

| Backend | 物理落点 | 跨 worker 共享 | 异步 | 重启后还在 |
|---|---|---|---|---|
| `MemorySaver` | 进程内存（dict） | ❌ 仅单进程 | — | ❌ 丢失 |
| `AsyncSqliteSaver` | 磁盘 SQLite 文件（如 `checkpoints.db`） | ❌ 文件锁，多进程不稳 | ✅ | ✅ |
| `AsyncPostgresSaver` | Postgres 三张表 `checkpoint` / `checkpoint_blobs` / `checkpoint_writes` | ✅ | ✅ | ✅ |
| `AsyncRedisSaver` | Redis（内存，可配 RDB/AOF 落盘） | ✅ | ✅ | 看 Redis 持久化配置 |

本仓库 `docker-compose.yml` 现有 **mysql / redis / qdrant**，**没有 Postgres**。现实候选：

- **最贴合：接 `AsyncRedisSaver`** —— Redis 已有、天然异步，和 `uvicorn --workers 4`
  多进程共享无痛；图状态是短暂会话态，放 Redis（带 TTL）语义最合适。
- `AsyncPostgresSaver` —— 要新起 Postgres，与现有 aiomysql 是两套库，运维成本最高。
- `AsyncSqliteSaver` —— 本地可跑，但文件锁扛不住 4 worker 并发写，生产不推荐。

> 注意：**checkpointer 的落盘 ≠ 现有的 `MessageService` 落盘**。前者写 Redis/Postgres，
> 存机器态供 LangGraph 续跑；后者写 MySQL，存可读消息流供前端拉会话列表。两者并存。

---

## 4. 配置方式：图级别，不是节点级别

checkpointer 在**编译时**一次性挂上，**没有「给某个节点加 @checkpoint」的写法**：

```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph

builder = StateGraph(dict)
# ... 加节点 / 边 ...
graph = builder.compile(checkpointer=MemorySaver())   # 图级配置
```

挂上后，**所有节点**的产出（state 更新）都按 `thread_id` 自动写进后端，你无需在任何节点里
写「保存」。对应本仓库的图：

```
input_normalizer → intent_router → state_tracker → policy_layer
   → (分支) → clarification_node | agent_node | handoff_node | response_generator
   → context_compressor → END
```

接上 checkpointer 后，上面**每个箭头跑完**都会自动快照一份。

---

## 5. 触发时机：每个 step（节点边界）自动

LangGraph 的 step = 一个节点执行单元。图每跑完一个节点，checkpointer 就把整份图状态存一份
（带 `checkpoint_id`）。你控制不了「哪几个节点存、哪几个不存」——要么全存，要么不挂。

调用时通过 `config` 携带 `thread_id` 来绑定线程：

```python
result = await graph.ainvoke(
    inputs,
    config={"configurable": {"thread_id": "session-demo-001"}},
)
```

流式同理：`await graph.astream(inputs, config=...)`.

---

## 6. 暂停恢复 / 时间旅行（interrupt）

「停在某个节点」是 `interrupt` 机制，它**底层复用 checkpointer**，但指定方式点名节点：

```python
# 方式 A：编译时声明在哪些节点「之前」暂停
graph = builder.compile(
    checkpointer=saver,
    interrupt_before=["agent_node"],   # 进 agent_node 前暂停等人确认
)

# 方式 B：在节点函数内部主动暂停（更细粒度）
from langgraph.types import interrupt

def agent_node(state: dict) -> dict:
    if state.get("needs_refund_approval"):
        # 暂停，把控制权交还调用方；resume 时 interrupt() 返回用户给的值
        confirm = interrupt({"question": "确认提交退款？"})
        if not confirm.get("approved"):
            return {"current_action": "answer_directly"}
    ...
```

恢复对话（带同一个 `thread_id` 再调一次即可，checkpointer 从断点续跑）：

```python
result = await graph.ainvoke(
    None,   # 或补充输入
    config={"configurable": {"thread_id": "session-demo-001"}},
)
```

时间旅行——从任意一步分叉：

```python
await graph.ainvoke(
    inputs,
    config={"configurable": {"thread_id": T, "checkpoint_id": C_3}},
)
```

> 对本项目的含义：想给「退款授权」加「暂停等人确认」，正确做法是
> `interrupt_before=["agent_node"]` 或在 `agent_node` 内 `interrupt()`，配合一个
> async saver。节点「暂停点」和「持久化后端」是两层正交概念。

---

## 7. 接入本项目的落地方案（建议：Redis）

### 7.1 依赖与连接

```python
# graph.py 中
import redis.asyncio as redis
from langgraph.checkpoint.redis.aio import AsyncRedisSaver


async def _build_checkpointer():
    client = redis.Redis(host="redis", port=6379, db=0, decode_responses=False)
    saver = AsyncRedisSaver(client)
    await saver.setup()          # 首次建索引
    return saver
```

> 注意：上面的 Redis 连接参数应与 `docker-compose.yml` 中 redis 服务一致；
> `decode_responses=False` 是 saver 序列化所需。

### 7.2 编译时挂载

```python
saver = await _build_checkpointer()
self.graph = builder.compile(checkpointer=saver)
```

### 7.3 调用时绑定 thread_id

把 `session_id` 当作 `thread_id`（前端已有会话概念，天然对应）：

```python
config = {"configurable": {"thread_id": state.session_id}}
if stream:
    async for ev in self.graph.astream(state_dict, config=config):
        ...
else:
    result = await self.graph.ainvoke(state_dict, config=config)
```

### 7.4 与现有 MessageService 并存

- **保留** `MessageService.persist`（写 MySQL）：负责前端消息流 / 会话列表，checkpointer 替代不了。
- **新增** checkpointer（写 Redis）：负责图态 continuity + interrupt + 重放。
- 你那套「图跑完、发 `final` 之前批量落库」的时序保证仍然成立——checkpointer 是图内部每步自动存，
  与边界批量落库是两条独立路径，互不冲突。

### 7.5 TTL 与删除清理

checkpointer 存的是短暂会话态，需防 Redis 无限增长 + 孤儿 key：

- **TTL**：通过 `app/config/checkpoint_config.py` 的 `CheckpointConfig.ttl_seconds` 配置
  （默认 7 天 = 604800）。`0` 表示不过期。优先级：`CHECKPOINT_TTL_SECONDS` 环境变量 >
  `llm_config.{env}.yml` 的 `checkpoint.ttl_seconds` 段 > 默认值。
  活跃会话每轮落库会刷新过期时间，仅长期空闲的会话被回收。
  `graph.py:_build_checkpointer` 把该值传给 `AsyncRedisSaver(ttl=...)`（`0`/`None` 视为不过期）。
- **删除清理**：`DELETE /chat/session/{id}` 在软删 MySQL 会话后，调用
  `agent.clear_checkpoint(session_id)`（=`thread_id`）显式 `adelete_thread` 清掉 Redis key，
  避免软删后 key 成孤儿、或同 `session_id` 复用时复活旧图态。清理失败仅记日志，不阻断删除。

> Redis key 默认带 `checkpoint:` 前缀，可直接与 qdrant / 其他 Redis 用途区分。

### 7.6 退款授权示例（interrupt）

```python
# agent_node 内，提交退款工具前暂停
from langgraph.types import interrupt

def _run_agent_node(state: dict) -> dict:
    if state.get("current_main_intent") == "after_sale_refund" and _needs_approval(state):
        decision = interrupt({"type": "refund_confirm", "order_id": state["slots"].get("order_id")})
        if not decision.get("approved"):
            return {"current_action": "answer_directly", "reply": "已取消退款。"}
    # 否则正常调用工具 ...
```

前端在 SSE 里收到一个 `__interrupt__` 事件（携确认问题），用户点确认后，带相同
`session_id` 再次请求 `/chat/stream` 且 `message` 为确认结果，图从断点续跑。

---

## 8. 取舍与建议

| 维度 | 手写（现状） | 接 Checkpointer |
|---|---|---|
| 跨轮状态恢复 | 自己从 DB 重建 state | `thread_id` 自动注入 |
| 前端消息流 | ✅ MySQL 必需 | ❌ 不覆盖，仍需手写 |
| 多 worker 共享 | ✅ aiomysql 已支持 | 需 Redis/Postgres saver |
| 暂停等人确认 | 手搓 state 标志 | `interrupt()` 原生 |
| 重放调试 | ❌ | ✅ |
| 运维成本 | 无新增 | 多一套存储 |

**建议**：当前 MVP 五能力（查订单/物流/退款咨询/转人工/闲聊）复杂度下，手写够用，**暂不引入**。
当出现以下需求时再局部接入最划算：
- Phase 4 多 action 涉及「退款需用户二次确认」→ 用 `interrupt()` 替代手搓标志；
- 需要客服坐席 / 开发回放排查对话 → 用 checkpoint 重放。

---

## 9. 参考文档与博客

官方文档（权威，优先阅读）：

- LangGraph 持久化概念：<https://langchain-ai.github.io/langgraph/concepts/persistence/>
- 如何添加 checkpointer：<https://langchain-ai.github.io/langgraph/how-tos/persistence/#add-checkpointer>
- 底层（StateGraph / 编译）概念：<https://langchain-ai.github.io/langgraph/concepts/low_level/>
- 暂停 / 恢复（interrupt）：<https://langchain-ai.github.io/langgraph/how-tos/interrupt/>
- Redis checkpointer 用法：<https://langchain-ai.github.io/langgraph/reference/checkpoints/#langgraph.checkpoint.redis.aio.AsyncRedisSaver>
- Postgres checkpointer 用法：<https://langchain-ai.github.io/langgraph/reference/checkpoints/#langgraph.checkpoint.postgres.aio.AsyncPostgresSaver>
- LangGraph 官方博客（含实战文章）：<https://blog.langchain.dev>

> 提示：以上为官方稳定链接；具体 API 名（如 `AsyncRedisSaver.from_conn_info`、
> `saver.setup()`）以你所装 `langgraph` / `langgraph-checkpoint` 版本的实际文档为准，
> 接入前请用 `pip show langgraph` 核对版本并对照对应版本文档。
