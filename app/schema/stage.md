# ConversationState 字段职责梳理

`app/schema/state.py` 中 `ConversationState` 的当前字段（共 24 个）。已移除的冗余字段：`candidate_intents` / `risk_level` / `topic_changed` / `latest_action_name` / `latest_action_result` / `current_form_name` / `current_form_slot_states` / `archived_states` / `clarification_count`。

说明：每个字段标注「写入位置 → 读取位置 → 职责」，便于判断是否存在重复或死状态。

## 主键与路由元数据

- `session_id: str` — 会话唯一标识。贯穿图执行（`thread_id`）、DAO 落库、SSE 事件。必需。
- `user_id: int` — 用户 ID。`dao/session.py` 落库与归属校验。必需。
- `channel: str` — 渠道（如 `web`）。`graph.py` 写入 payload、DAO 落库。必需。

## 意图与槽位

- `current_main_intent: MainIntentCode` — 当前主意图码（默认 `unrecognize`）。状态机核心，前端/路由/prompt 均依赖。
- `current_sub_intent: SubIntentCode` — 子意图码（默认 `unrecognize.unknown`）。
- `stage: str` — 处理阶段机（默认 `new`），取值：`handoff` / `collecting_info` / `executing` / `responding` / `unsupported`。由 `routing.apply()` 按意图与槽位情况赋值。驱动前端状态面板展示、`prompts/system.py` 拼 prompt、`routing.py` 日志。
- `slots: dict[str, str]` — 已抽取槽位的**实际值**（如 `{order_id: "A1001"}`）。工具执行的硬依赖：`tool_executor.py` 每处 `state.slots.get("order_id")` 取值；`prompts/system.py` / `state_summary.py` 拼进上下文。必需，不可删。
- `missing_slots: list[str]` — 还缺的槽位 key 列表。由 `routing.py` 现算（`[s for s in required_slots if not state.slots.get(s)]`，派生量）。决定 `stage=collecting_info` 与是否追问。
- `confirmed_slots: list[str]` — 已确认槽位 key 列表。跨意图继承时去重追加（`routing.py`）。派生量。

## 情绪与澄清

- `emotion: EmotionState` — 情绪与置信度。`routing.py` 读取参与置信度决策（`state.emotion.primary == "negative"` 时下调 confidence）。
- `needs_clarification: bool` — 是否需澄清。控制进入 clarification 节点；前端 snapshot 展示；`routing.py` 多意图守卫判断。
- `slot_clarification_count: int` — 槽位澄清轮次计数。达 `handoff_threshold` 转人工（`routing.py` 阈值判断）。
- `intent_clarification_count: int` — 意图澄清轮次计数。同上阈值判断。

## 执行流

- `current_action: str` — 策略层决策出的动作码（如 `handoff_human` / `ask_intent_clarification` / `ask_slot_clarification` / `agent_process` / `answer_directly`），由 `routing.py` 的 `HandoffClarificationPolicy.decide` 赋值。驱动 `graph.route_after_policy` 分支路由 + `prompts/system.py` 拼 prompt。`message.py` 据其判断落库消息类型（`clarification` / `text`）。
- `action_history: list[ActionRecord]` — 动作审计流水。各节点 append（`clarification_node` / `response_generator` / `handoff_node`）。唯一消费点：`response.py` 去重（避免重复追加 `response_generator`）；另作可追溯审计。

## 上下文与产物

- `summary: str` — 每轮一句话状态快照（`build_state_summary`，**纯内存字符串拼接，不调 LLM**）。仅下发前端状态面板（`graph.py` snapshot → 前端显示）。其内容与同 snapshot 内的结构化字段重复。
- `running_summary: str` — 活动窗口**之外**的历史折叠叙述。喂 LLM 上下文（`agent_node.py` 前置进 prompt）。写入：`context._fold_summary`（配 `summarizer` 时走 LLM 折叠，否则降级文本拼接+截断）。
- `recent_messages: list[dict[str, str]]` — 活动上下文窗口（最近 N 条原样）。喂 LLM（`agent_node.py` / `response.py` 拼消息）；溢出时裁掉 oldest 转交 `running_summary`。与 `running_summary` 互补（窗口内 vs 窗口外）。
- `intent_result: IntentResult | None` — 意图路由结果对象。`intent_router` 节点写入、`state_tracker` 节点读取，是图内两节点间的**传参载体**；`state_tracker.apply()` 已将其字段全部分解进 `current_main_intent` / `current_sub_intent` / `emotion` / `needs_clarification` / `slots` / `handoff` 等独立字段。每轮开头 `graph.py` 清空。
- `tool_result: ToolExecutionResult | None` — 最近一次工具执行结果（仅工具类动作有）。前端 `tool_result` 事件 + `prompts/system.py` 拼 prompt。`graph.py` 每轮开头清空。
- `reply: str` — 最终回复文本。各节点（`clarification` / `response` / `agent_node` / `graph` 续办提示）写入；`message.py` 落库、`graph.py` final 事件下发、前端渲染。每轮开头清空。

## 转人工与多意图

- `handoff: bool` — 是否转人工。`dao/session.py` 决定会话 status（`SESSION_STATUS_HANDOFF`）、`graph.py` 路由与 `pending_intents` 守卫、`routing.py` 阶段赋值。
- `handoff_reason: str` — 转人工原因。`graph.py` 日志、`routing.py` 赋值（含 `clarification_failed`）。
- `pending_intents: list[PendingIntent]` — 排队待处理的次要意图（多意图续办）。`routing._handle_pending_intents` 入队/激活；`graph.py` 续办提示与守卫读取。

## 关联模型（内嵌类型）

- `ActionRecord`（`action_history` 元素）：`action_name` / `status` / `summary` / `created_at`。
- `ToolExecutionResult`（`tool_result` 类型）：`kind` / `raw_result` / `sanitized_result` / `user_facing_summary`。
- `PendingIntent`（`pending_intents` 元素）：`main_intent` / `sub_intent` / `slots` / `confidence` / `reason`。
- `IntentResult`（`intent_result` 类型）：意图层完整结果，见 `app/schema/intent.py`。

## 精简历史

- `slots` 必须保留（承载工具执行所需实际值）；`missing_slots` / `confirmed_slots` 为其派生量。
- `summary` 不喂 LLM，与前端已收到的结构化字段重复，可酌情删除（需前端改用结构化字段展示）。
- `latest_action_result`、`candidate_intents`、`risk_level`、`topic_changed`、`latest_action_name`、`archived_states`、`clarification_count`、`current_form_name`、`current_form_slot_states` 经核查为死状态/只写不读，已移除。
