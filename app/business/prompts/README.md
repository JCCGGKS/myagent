# app/business/prompts 模块

LLM 提示词**定义与构造**层：集中存放各节点的 system / user 提示词模板与构造器。
对话产出所需的**示例内容**由 `dialog/` 从 `config/*.yml` 加载后注入（见 `dialog/README.md`），本模块不持有示例配置，只提供提示词骨架与拼装逻辑。

## 文件职责

### `intent.py` — 意图识别提示词
- `LLM_INTENT_SYSTEM_PROMPT`：意图分类器的系统提示（约束只能从给定意图中选择、输出合法 JSON、不编造意图）。
- `_group_sub_intents()` / `_build_intent_lists()`：基于 `app.schema.intent` 的权威枚举 `MAIN_INTENT_CODES` / `SUB_INTENT_CODES` **动态生成**可选主/子意图列表，新增意图无需改提示词代码。
- `build_llm_intent_user_prompt(message, previous_sub_intent)`：构造意图识别的 user 提示，内嵌判定原则（问候 / 转人工 / 订单 / 物流 / 退款售后 / 投诉 / 超范围 / 未覆盖）与多轮上下文（上一轮子意图）。

### `system.py` — 对话节点提示词
- `SYSTEM_PROMPT_PREFIX`：客服助手前缀常量。
- `_build_base_system_prompt(state)`：构造公共上下文部分（当前意图、阶段、已填/缺失槽位），供各对话节点复用。
- `build_agent_system_prompt(state)`：Agent 调度节点提示——只做决策与工具调用，不输出最终回复。
- `build_clarification_system_prompt(state, examples=None)`：澄清节点提示——生成追问话术；`examples` 由 `dialog` 注入示例参考。
- `build_response_system_prompt(state, examples=None)`：回复生成节点提示——含工具结果，要求语气与示例一致；`examples` 由 `dialog` 注入示例参考。
- `_append_examples(prompt, examples)`：把示例拼为固定的 `【回复示例参考】` 小节。

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
