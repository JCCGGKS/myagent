# app/business/prompts 模块

LLM 提示词**定义与构造**层：集中存放各节点的 system / user 提示词模板与构造器。
对话产出所需的**示例内容**由 `dialog/` 从 `config/*.yml` 加载后注入（见 `dialog/README.md`），本模块不持有示例配置，只提供提示词骨架与拼装逻辑。

## 文件职责

### `intent.py` — 意图识别提示词
- `LLM_INTENT_SYSTEM_PROMPT`：意图分类器的系统提示（约束只能从给定意图中选择、输出合法 JSON、不编造意图）。
- `_group_sub_intents()` / `_build_intent_lists()`：基于 `app.schema.intent` 的权威枚举 `MAIN_INTENT_CODES` / `SUB_INTENT_CODES` **动态生成**可选主/子意图列表，新增意图无需改提示词代码。
- `build_llm_intent_user_prompt(message, previous_sub_intent="", state=None)`：构造意图识别的 user 提示，内嵌判定原则（问候 / 转人工 / 订单 / 物流 / 退款售后 / 投诉 / 超范围 / 未覆盖）与多轮上下文（上一轮子意图）。传入 `state` 时优先从状态对象借用上下文（`state.current_sub_intent`），同样只取对意图识别有用的字段，避免透传整份状态。

### `system.py` — 对话节点提示词
- `SYSTEM_PROMPT_PREFIX`：客服助手前缀常量。
- **按节点隔离的字段白名单**：每个助手只取「对它执行有帮助」的状态字段，互不相同——
  - `AGENT_FIELDS`：`当前意图 / 阶段 / 已填槽位 / 缺失槽位 / 当前动作`（调度节点决策调工具用，**不含情绪**，因为它不生成面向用户的文本）。
  - `CLARIFICATION_FIELDS`：`当前意图 / 阶段 / 已填槽位 / 缺失槽位 / 当前动作 / 情绪`（澄清节点生成追问用，借情绪定语气）。
  - `RESPONSE_FIELDS`：`当前意图 / 阶段 / 已填槽位 / 已确认槽位 / 情绪 / 是否需要澄清`（最终回复节点组织友好回复用，**不含当前动作 / 缺失槽位**，因为回复是收尾）。
  - 白名单之外的字段（`session_id` / `user_id` / `channel` / `action_history` / `running_summary` / `recent_messages` / `pending_intents` / 各类计数器 / `reply` 等）**一律不进入任何提示词**。
- `build_prompt_context(state, fields)`：**上下文隔离**入口。从状态对象按给定白名单抽取非空字段，得到只属于该节点的「提示词可见」切片。
- `_render_base_context(ctx)`：把隔离后的切片渲染成公共片段（意图/阶段/槽位/情绪等，按 ctx 中实际存在的字段渲染）。
- `build_agent_system_prompt(state)`：Agent 调度节点提示——只做决策与工具调用，不输出最终回复；`tools=` 参数另发工具 schema，提示词不罗列。
- `build_clarification_system_prompt(state, examples=None)`：澄清节点提示——生成追问话术；基于 `CLARIFICATION_FIELDS` 隔离切片（含当前动作、缺失槽位、情绪）。`examples` 由 `dialog` 注入。
- `build_response_system_prompt(state, examples=None)`：回复生成节点提示——基于 `RESPONSE_FIELDS` 隔离切片（含情绪、已确认槽位、是否需要澄清），并显式透传执行产物 `tool_result`（仅此节点需要）。`examples` 由 `dialog` 注入。
- `_append_examples(prompt, examples)`：把示例拼为固定的 `【回复示例参考】` 小节。

> **上下文隔离原则**：三个对话节点的提示词**各自从自己的字段白名单**取数，而非共享一份或读 `state` 任意字段。某个状态字段要透传给特定助手，只需加入对应的 `*_FIELDS` 白名单；对执行无帮助的字段默认隔离，无需在提示词里逐个排除。

## 分层与依赖

- 依赖方向：`prompts → schema`（读取 `ConversationState` 与意图枚举），向下无环。
- 不依赖 `dao` / `config`：示例配置与 YAML 加载由 `dialog/` 负责，本模块保持纯提示词构造。
- 外部统一从包入口导入，例如：

```python
from app.business.prompts import (
    build_clarification_system_prompt,
    build_response_system_prompt,
    build_agent_system_prompt,
    build_llm_intent_user_prompt,
)
```
