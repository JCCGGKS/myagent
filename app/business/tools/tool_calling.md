# Agent 节点设计说明

本目录是客服 Agent 的「工具编排」层（与意图路由、`state_tracker`、`response_generator` 协作）：

- `agent_node.py` —— `AgentNodeService`，负责决策是否调用工具、执行工具、把结果回灌上下文，本身**不生成最终回复**（`state.reply` 由 `response_generator` 写）。
- `graph.py` —— `CustomerServiceAgent`，用 LangGraph `StateGraph` 把各节点串成 `input_normalizer → intent_router → state_tracker → policy_layer → {clarification_node | agent_node | handoff_node | response_generator} → context_compressor`。

本文档聚焦两个问题：**ReAct 提示词 vs API Function Calling 的区别与选型**，以及**如何用 Function Calling 做多工具并行调度**。

---

## 1. ReAct 提示词 vs API Function Calling

两者目标相同：让 LLM「先想、再调工具、看结果、再想」，循环直到能回答。区别在于**推理-行动的循环由谁驱动**。

### 1.1 实现方式

**ReAct（提示词驱动）**
- 把 `Thought / Action / Action Input / Observation` 拼进 prompt，让模型**以纯文本续写**行动与观察。
- 框架负责正则解析模型输出里的 `Action:` 和 `Observation:`，执行工具后再把观察拼回 prompt。
- 本仓库**未采用**此形式——`build_agent_system_prompt` 里没有 Thought/Action 脚手架，只告诉模型「需要信息就调工具，够了就结束」。

**API Function Calling（结构化驱动）**
- 给 LLM 传入 `tools` 参数（JSON Schema 描述每个工具的名字、参数、用途）。
- 模型以**结构化字段** `tool_calls` 返回动作，不直接吐文本。
- 框架执行工具，把结果以 `role: "tool"` 消息回灌，再进入下一轮。
- 本仓库采用此形式：`AgentNodeService.run` 循环调 `call_llm_async(..., tools=self.tools)`，`response["tool_calls"]` 非空就执行并 `continue`，为空则 `break`（`agent_node.py:43-71` 的 `run` 循环，`agent_node.py:102-111` 的 `_call_llm` 内经 `utils/llm.py:77` 透传 `tools=tools`）。

> **工具信息只从 `tools=` API 参数注入，不进 prompt**：工具 schema 由 `graph.py:147` 装配 `AgentNodeService` 时 `tools=build_tool_schemas()` 注册，经 `agent_node` 的 `self.tools` → `call_llm_async(tools=self.tools)` 下发。系统提示（`build_agent_system_prompt`）**刻意不罗列**工具名称/描述——避免与 `tools=` 参数里的结构化 schema 重复（同一份信息既占 token 又冗余）。模型选工具依赖 `tools=` 参数，prompt 只需告诉它「需要信息就调工具，够了就结束」。

### 1.2 不同要求

| 维度 | ReAct（提示词） | Function Calling（API） |
| --- | --- | --- |
| 模型能力 | 任意能续写文本的模型都可用 | 需要模型原生支持 tool/function calling |
| 工具描述 | 写进 prompt 的自然语言段落 | 严格 JSON Schema，字段需类型明确 |
| 动作解析 | 正则/字符串解析，易因格式漂移出错 | 结构化字段，解析可靠 |
| 多工具并行 | 需自己设计文本协议，脆弱 | 模型一次可返回多个 `tool_calls`，天然支持 |
| 可控性 | 强（prompt 可精细约束推理风格） | 弱（依赖模型对 schema 的理解，黑盒） |
| 调试 | 输出可读、可人工审阅推理链 | 推理链在 `tool_calls` 里，需另记日志 |

### 1.3 选型与适用场景

- **选 ReAct 提示词当**：模型不支持 function calling（本地小模型、某些开源模型）；需要把推理过程完全暴露成可读文本（教学、审计）；工具集简单、变化少。
- **选 Function Calling 当**：使用 OpenAI / Anthropic / 主流支持 tool use 的模型；追求动作解析稳定、低出错率；需要多工具并行、复杂工具编排；生产环境要可控的延迟与错误率。
- **本仓库选型**：Function Calling。理由——已用 OpenAI 客户端（`app/utils/llm.py`），工具 schema 已集中在 `tool_executor.py` 的 `TOOLS` 注册表，且需要稳定的工具分发（订单/物流/转人工/RAG）。

---

## 2. 用 Function Calling 实现多工具并行调度

### 2.1 现状

`AgentNodeService.run` 每轮只处理模型**这一轮**返回的 `tool_calls`，但 `ToolExecutor.run` 内部是**串行**循环（`tool_executor.py:167`）：

```python
for tc in tool_calls:
    result = self._execute_one(name, args, state)   # 逐个执行
    tool_messages.append(...)
```

即：模型一次可能返回多个 `tool_calls`，但当前是「一个跑完再跑下一个」。因为同一轮里的 `tool_calls` 互不依赖（模型在同一响应里一起给出，期望全部解决后再进入下一轮推理），**它们本应可以并行**。

### 2.2 并行调度设计

核心思路：同一轮内的多个 `tool_calls` 之间没有数据依赖，用并发原语同时执行，收集全部结果后再回灌。

- **线程池（同步接口，改动最小）**：把 `ToolExecutor.run` 的循环改成 `ThreadPoolExecutor` 并发 `map`（`query_order` 查库、`query_logistics` 调外部 API、`rag_retrieve` 向量检索都是 I/O 密集型，并发能显著压低总延迟）。
- **异步（asyncio，配合异步工具客户端）**：若工具客户端本身是 `awaitable`（如 `httpx.AsyncClient`、`asyncpg`），用 `asyncio.gather` 并发——延迟最优，但要求工具层全部异步化（本仓库当前是同步 `OrderService`/`LogisticsService`，需改造）。

### 2.3 依赖感知的「并行 + 串行」调度

更真实的多轮场景里，工具之间存在依赖（B 需要 A 的结果）。调度策略：

1. 第一轮：模型给出无依赖的多个 `tool_calls` → 全部并行执行；
2. 结果回灌后，模型基于观察再决定下一轮（可能又是一组可并行的 `tool_calls`）；
3. 如此逐轮推进，轮内并行、轮间串行——正是 `AgentNodeService` 的 `for _round` 循环 + 轮内并发的组合。

> 关键约束：**只有同一轮内的 `tool_calls` 可安全并行**。跨轮必须串行，因为后一轮的推理依赖前一轮的观察。

### 2.4 注意事项

- **结果顺序**：`tool_calls` 与 `role: "tool"` 消息靠 `tool_call_id` 一一对应，并行后仍需按 `tool_call_id` 回填，不能只靠列表顺序。
- **失败隔离**：单个工具超时/报错不应阻塞同轮其他工具——用 `try/except` 包裹每个 `_execute_one`，错误也作为 `tool` 消息回灌，让模型自己决定降级。
- **限流**：并发调用外部 API 要加信号量/`max_workers`，避免打爆下游。
- **幂等**：并行工具最好是只读/幂等的（`query_order`/`query_logistics`/`rag_retrieve` 都是）；带副作用的工具（如 `create_handoff`）应**禁止并行**，且最好单轮只调一次。
- **最大轮次**：保留 `max_tool_rounds`（本仓库=3）防止无限循环。

### 2.5 落地优先级

1. 先把 `ToolExecutor.run` 的串行循环换成线程池并发（低风险、立竿见影）；
2. 给 `create_handoff` 等副作用工具加「单轮去重 / 禁用并行」标记；
3. 工具层异步化后，再升级到 `asyncio.gather` 方案。

---

## 3. 参考资源

- ReAct 原始论文（推理+行动范式）：Yao et al., 2022, *ReAct: Synergizing Reasoning and Acting in Language Models* —— https://arxiv.org/abs/2210.03629
- OpenAI Function Calling / Tool Use 指南 —— https://platform.openai.com/docs/guides/function-calling
- Anthropic Tool Use 文档 —— https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- LangGraph（本仓库编排框架，含工具节点与状态图）—— https://langchain-ai.github.io/langgraph/
- OpenAI Swarm（多 agent / 多工具编排示例，教学向）—— https://github.com/openai/swarm
- LlamaIndex Function Calling / Agent 文档（工具抽象与并行检索参考）—— https://docs.llamaindex.ai/

> 注：以上为公开技术文档，链接以官方最新地址为准；具体 API 字段随模型版本演进，落地前对照所用模型的当前文档。
