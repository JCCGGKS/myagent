# 上下文管理（context）

`app/business/context` 负责**对话上下文的窗口管理与摘要压缩**，让长会话的模型上下文保持有界、连贯，而不是无限制地把全部历史塞给 LLM。

模块内文件：

- `context.py`：`ContextService`，活动窗口 + 摘要缓冲的核心逻辑。
- `state_summary.py`：`build_state_summary`，每轮一句话状态快照（与叙述性摘要职责分离）。

> 本模块只管上下文压缩，不负责意图识别、工具编排、回复生成（见 `app/business` 各子包）。

---

## 设计原则

1. **活动窗口（window）**：模型每轮只看「最近 N 条原样消息」，`recent_messages` 承载。
2. **摘要缓冲（buffer）**：窗口之外的老消息持续折叠进 `running_summary`，由 LLM 折叠器或有界拼接维护。
3. **回灌（injection）**：`running_summary` 作为前置上下文注入模型 messages，使窗口外的信息仍可见。
4. **配置化**：窗口大小与摘要上限来自独立 `context:` 配置段，不硬编码。

---

## 相关状态字段（`app/schema/state.py`）

| 字段 | 角色 |
|---|---|
| `recent_messages` | 活动窗口：原样保留的近期消息（上限 `max_recent_messages`） |
| `running_summary` | 摘要缓冲：窗口外消息折叠后的连贯摘要，已回灌模型 |
| `summary` | 每轮一句话状态快照（意图/槽位/最近动作），用于状态展示，非叙述缓冲 |
| `archived_states` | 话题切换时归档的旧任务状态，腾出上下文 |

> `message_history` 字段已移除：原「无界历史」被 `recent_messages + running_summary` 取代，既不参与模型上下文也不落库，仅写不读。

---

## 调用链路

以一次用户提问为例，上下文相关步骤：

1. **入消息**（`agent/graph.py` `input_normalizer`）：用户消息 append 进 `recent_messages`。
2. **Agent 决策节点**（`agent/agent_node.py` `_build_messages`）：
   ```
   [系统提示] + [running_summary 前置上下文（若有）] + recent_messages
   ```
   不再发送无界的 `message_history`。
3. **回复生成节点**（`dialog/dialog.py` `_build_messages`）：与上面结构一致，同样基于 `running_summary + recent_messages`。
4. **上下文压缩节点**（`agent/graph.py` `context_compressor` → `ContextService.compress`）：
   - 助手回复 append 进 `recent_messages`；
   - 若 `recent_messages` 超过 `max_recent_messages`，溢出部分经 `_fold_summary` 折叠进 `running_summary`；
   - 每轮重算 `state.summary`。

---

## ContextService

### `compress(state)`
- 把本轮助手回复写入活动窗口 `recent_messages`。
- 窗口溢出 → 取溢出消息，调用 `_fold_summary` 折叠进 `running_summary`，窗口截留最后 `max_recent_messages` 条。
- 重算 `state.summary = build_state_summary(state)`。

### `_fold_summary(old_summary, overflow)`
- **有 `summarizer`**：交给 LLM 把「旧摘要 + 溢出消息」合并为连贯中文摘要，保持有界。
- **无 / 失败**：退化为 `"role:content"` 拼接，并截断到 `max_summary_chars`，避免无限增长。
- 折叠异常被吞掉，降级为拼接，不影响主流程。

### `summarizer` 钩子
- 可选注入的 `Callable[[str, list[dict]], str]`（在 `agent/graph.py` 用 `llm_client` 构造，见 `_make_summary_fold_fn`）。
- 不传则走拼接退化模式；LLM 不可用或调用失败也会自动降级。
- 以依赖注入方式传入，保持本模块为叶子层（不直接依赖 LLM 客户端）。

---

## 配置（`app/config/context_config.py`）

独立顶层 `context:` 段（基础设施配置，改 YAML 后重启生效，不由前端管理）：

```yaml
context:
  max_recent_messages: 6   # 活动窗口消息条数（约 3 轮问答，非轮数）
  max_summary_chars: 2000 # 退化模式下 running_summary 的最大长度
```

`graph.py` 构造 `ContextService` 时通过 `get_context_config_service().get_config()` 读取并注入。

---

## 边界与注意

- **`max_recent_messages` 是消息条数，不是轮数**：1 轮 = 1 用户 + 1 助手 = 2 条；6 条 ≈ 3 轮（严格交替时）。
- **`summary` 与 `running_summary` 不同**：前者是模板拼接的一句话状态快照（无 LLM），后者是叙述性缓冲（LLM 折叠优先）。
- **折叠只在窗口溢出时发生**，短会话不触发额外 LLM 调用。
- **`running_summary` 必须回灌**：若某节点构造 messages 时漏掉它，摘要缓冲即失效（当前 agent_node / dialog 均已注入）。
