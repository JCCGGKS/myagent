# Agent 节点：工具编排设计（Tool Orchestration in agent_node）

本目录是客服 Agent 的「工具编排」层（与意图路由、`state_tracker`、`response_generator` 协作）：

- `agent_node.py` —— `AgentNodeService`，负责决策是否调用工具、执行工具、把结果回灌上下文，本身**不生成最终回复**（`state.reply` 由 `response_generator` 写）。
- `graph.py` —— `CustomerServiceAgent`，用 LangGraph `StateGraph` 把各节点串成 `input_normalizer → intent_router → state_tracker → policy_layer → {clarification_node | agent_node | handoff_node | response_generator} → context_compressor`。

本文档聚焦两件事：**① 两种驱动方式（ReAct 提示词 vs API Function Calling）与选型/兜底**；**② 参考资源**。多工具调用的编排模式、问题与并行调度设计统一收口在 `tool编排.md`（避免重复）。

---

# 一、驱动方式：ReAct 提示词 vs API Function Calling

两者目标相同：让 LLM「先想、再调工具、看结果、再想」，循环直到能回答。区别在于**推理-行动的循环由谁驱动**。

## 1.1 实现方式

**ReAct（提示词驱动）**
- 把 `Thought / Action / Action Input / Observation` 拼进 prompt，让模型**以纯文本续写**行动与观察。
- 框架负责正则解析模型输出里的 `Action:` 和 `Observation:`，执行工具后再把观察拼回 prompt。
- 本仓库**未采用**此形式——`build_agent_system_prompt` 里没有 Thought/Action 脚手架，只告诉模型「需要信息就调工具，够了就结束」。

**API Function Calling（结构化驱动）**
- 给 LLM 传入 `tools` 参数（JSON Schema 描述每个工具的名字、参数、用途）。
- 模型以**结构化字段** `tool_calls`（数组）返回动作，不直接吐文本。
- 框架执行工具，把结果以 `role: "tool"` 消息回灌，再进入下一轮。
- 本仓库采用此形式：`AgentNodeService.run` 循环调 `call_llm_async(..., tools=self.tools)`，`response["tool_calls"]` 非空就执行并 `continue`，为空则 `break`（`agent_node.py:43-71` 的 `run` 循环，`agent_node.py:102-111` 的 `_call_llm` 内经 `utils/llm.py:77` 透传 `tools=tools`）。

> **工具信息只从 `tools=` API 参数注入，不进 prompt**：工具 schema 由 `graph.py:147` 装配 `AgentNodeService` 时 `tools=build_tool_schemas()` 注册，经 `agent_node` 的 `self.tools` → `call_llm_async(tools=self.tools)` 下发。系统提示（`build_agent_system_prompt`）**刻意不罗列**工具名称/描述——避免与 `tools=` 参数里的结构化 schema 重复（同一份信息既占 token 又冗余）。模型选工具依赖 `tools=` 参数，prompt 只需告诉它「需要信息就调工具，够了就结束」。

## 1.2 维度对比

| 维度 | ReAct（提示词） | Function Calling（API） |
|---|---|---|
| 模型能力 | 任意能续写文本的模型都可用 | 需要模型原生支持 tool/function calling |
| 工具描述 | 写进 prompt 的自然语言段落 | 严格 JSON Schema，字段需类型明确 |
| 动作解析 | 正则/字符串解析，易因格式漂移出错 | 结构化字段，解析可靠 |
| 多工具并行 | 需自己设计文本协议，脆弱 | 模型一次可返回多个 `tool_calls`，天然支持 |
| 可控性 | 强（prompt 可精细约束推理风格） | 弱（依赖模型对 schema 的理解，黑盒） |
| 调试 | 输出可读、可人工审阅推理链 | 推理链在 `tool_calls` 里，需另记日志 |

## 1.3 选型（本仓库 = Function Calling）

- **选 ReAct 提示词当**：模型不支持 function calling（本地小模型、某些开源模型）；需要把推理过程完全暴露成可读文本（教学、审计）；工具集简单、变化少。
- **选 Function Calling 当**：使用 OpenAI / Anthropic / 主流支持 tool use 的模型；追求动作解析稳定、低出错率；需要多工具并行、复杂工具编排；生产环境要可控的延迟与错误率。
- **本仓库选型理由**：已用 OpenAI 客户端（`app/utils/llm.py`），工具 schema 已集中在 `tool_executor.py` 的 `TOOLS` 注册表，且需要稳定的工具分发（订单/物流/转人工/RAG）。

## 1.4 兜底：模型不支持 Function Calling → Prompt ReAct

当所用模型原生不支持 function calling 时，**把 ReAct 控制流从「API 原生 `tool_calls` 通道」搬到「prompt + 自解析」**：把工具 schema 写进 system prompt，要求模型按固定格式输出（如 `Action: name(args)` 或 JSON），框架解析这段文本 → 执行 → 结果拼回 prompt → 再让模型决策，循环同构。

本质没变：**还是 ReAct（想→调→看→再想），只是「调工具」的信号从结构化 `tool_calls` 字段变成自由文本，由你 parse**。代价（原生通道免费给的，prompt 版得自己造）：

- **格式不可靠** → 强制约束（严格 JSON / 专用分隔符）+ 健壮 parser + 解析失败重试。
- **更费 token / 更易错** → 工具 schema 占 prompt，模型可能不守格式，需多一轮纠错。
- **风险工具更要闸** → 文本解析出的「调退款」不能和原生一样直接执行，确认/policy 闸门一样不能少（甚至更严）。

项目对应点：已有的 `LLMIntentFallbackService` 是**意图级**的 prompt 兜底；工具级若要兜底，是套同样思路——一个「prompt 版 ToolExecutor」解析模型文本输出。最坏情况解析不出 → 转人工（落到全局兜底）。

---

# 二、参考资源

- ReAct 原始论文（推理+行动范式）：Yao et al., 2022, *ReAct: Synergizing Reasoning and Acting in Language Models* —— https://arxiv.org/abs/2210.03629
- OpenAI Function Calling / Tool Use 指南 —— https://platform.openai.com/docs/guides/function-calling
- Anthropic Tool Use 文档 —— https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- LangGraph（本仓库编排框架，含工具节点与状态图）—— https://langchain-ai.github.io/langgraph/
- OpenAI Swarm（多 agent / 多工具编排示例，教学向）—— https://github.com/openai/swarm
- LlamaIndex Function Calling / Agent 文档（工具抽象与并行检索参考）—— https://docs.llamaindex.ai/

> 注：以上为公开技术文档，链接以官方最新地址为准；具体 API 字段随模型版本演进，落地前对照所用模型的当前文档。
