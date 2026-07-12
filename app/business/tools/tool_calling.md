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
- 本仓库采用此形式：`AgentNodeService.run` 循环调 `call_llm(..., tools=self.tools)`，`response["tool_calls"]` 非空就执行并 `continue`，为空则 `break`（`agent_node.py:41-61`）。

### 1.2 不同要求

| 维度 | ReAct（提示词） | Function Calling（API） |
| --- | --- | --- |
| 模型能力 | 任意能续写文本的模型都可用 | 需要模型原生支持 tool/function calling |
| 工具描述 | 写进 prompt 的自然语言段落 | 严格 JSON Schema，字段需类型明确 |
| 动作解析 | 正则/字符串解析，易因格式漂移出错 | 结构化字段，解析可靠 |
| 多工具并行 | 需自己设计文本协议，脆弱 | 模型一次可返回多个 `tool_calls`，天然支持 |
| 可控性 | 强（prompt 可精细约束推理风格） | 弱（依赖模型对 schema 的理解，黑盒） |
| 调试 | 输出可读、可人工审阅推理链 | 推理链在 `tool_calls` 里，需另记日志 |

### 1.3 适用场景

**选 ReAct 提示词当：**
- 使用的模型不支持 function calling（本地小模型、某些开源模型）；
- 需要把推理过程完全暴露成可读文本（教学、审计、可解释性要求高）；
- 工具集简单、变化少，且你能接受解析的脆弱性。

**选 Function Calling 当：**
- 使用 OpenAI / Anthropic / 主流支持 tool use 的模型；
- 追求动作解析稳定、低出错率；
- 需要多工具并行、复杂工具编排；
- 生产环境，要可控的延迟与错误率。

**本仓库选型**：Function Calling。理由——已用 OpenAI 客户端（`app/utils/llm.py`），工具 schema 已集中在 `tool_executor.py` 的 `TOOLS` 注册表，且需要稳定的工具分发（订单/物流/转人工/RAG）。

### 1.4 如何选型（决策清单）

1. 模型是否支持 tool use？不支持 → ReAct 提示词；支持 → 进入 2。
2. 是否要并行调用多个工具？要 → Function Calling；否 → 进入 3。
3. 是否要强可控、可读的推理链？要 → ReAct 提示词（或 Function Calling + 强制输出 Thought）；否 → Function Calling。
4. 生产稳定性优先 → Function Calling。

> 折中：可在 Function Calling 的 system prompt 里要求模型先输出一句简短推理（Thought），兼顾稳定与可解释，本仓库当前未加。

### 1.5 两种方式的标准提示词模板

下面给出可直接落地的模板。Function Calling 模板**取自本仓库实际实现**，ReAct 模板为等价的文本驱动版本，方便对比。

#### 1.5.1 Function Calling 模板（本仓库采用）

**① System Prompt**（`build_agent_system_prompt` 主体，含意图/槽位上下文）

```text
你是一个客服助手，负责回答用户问题。
当前意图：order_query.query_status
当前阶段：slot_filling
已填槽位：{}
缺失槽位：['order_id']

你是客服助手的【调度节点】，只负责决定下一步动作：
1. 若需要更多信息来回答用户（如订单状态、物流、知识库内容），请调用合适的工具；
2. 若当前上下文已足够回答用户，请不要调用任何工具，直接结束本节点。
注意：你只做决策与工具调用，不要在此输出给用户的最终回复，最终回复由专门的回复节点生成。
```

**② Tools 定义**（节选自 `tool_executor.py` 的 `TOOLS` 注册表，JSON Schema 驱动 function calling）

```json
[
  {
    "type": "function",
    "function": {
      "name": "query_order",
      "description": "查询指定订单的状态、商品、金额等信息。当用户提供订单号并询问订单状态时调用。",
      "parameters": {
        "type": "object",
        "properties": { "order_id": { "type": "string", "description": "订单号" } },
        "required": ["order_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "query_logistics",
      "description": "查询指定订单的物流配送进度与最新节点。当用户询问快递到哪了、是否签收时调用。",
      "parameters": {
        "type": "object",
        "properties": { "order_id": { "type": "string", "description": "订单号" } },
        "required": ["order_id"]
      }
    }
  }
]
```

**③ LLM 返回（结构化 `tool_calls`，非文本）**

```json
{
  "tool_calls": [
    {
      "id": "call_abc",
      "type": "function",
      "function": { "name": "query_order", "arguments": "{\"order_id\": \"A1001\"}" }
    }
  ]
}
```

**④ 框架回灌观察**（工具执行后以 `role: "tool"` 追加，供下一轮推理）

```json
{ "role": "tool", "tool_call_id": "call_abc", "name": "query_order",
  "content": "{\"kind\":\"order_query\",\"user_facing_summary\":\"订单 A1001 当前状态为 已发货\"}" }
```

> 关键点：动作走结构化字段，框架按 `tool_call_id` 配对，无需解析文本。

#### 1.5.2 ReAct 提示词模板（文本驱动，等价能力）

**① System Prompt**（内嵌 Thought/Action/Observation 协议 + 少量示例）

```text
你是一个客服助手，可通过调用工具获取信息来回答用户。
请严格按照以下格式推理与行动，每轮只输出一个动作：

Thought: 你当前的推理，分析还缺什么信息、该调哪个工具
Action: 工具名（可选：query_order / query_logistics / create_handoff / rag_retrieve）
Action Input: 工具的 JSON 参数，如 {"order_id": "A1001"}
Observation: （由系统填充工具返回结果，你看到后继续下一轮）

当信息已足够回答用户时，输出：
Thought: 信息已足够
Action: Final Answer
Action Input: （留空）

示例：
用户：帮我查下订单 A1001 到哪了
Thought: 用户问物流，需调用 query_logistics，订单号 A1001 已知
Action: query_logistics
Action Input: {"order_id": "A1001"}
Observation: {"kind":"logistics","user_facing_summary":"订单 A1001 已签收"}
Thought: 物流信息已获取，可回答
Action: Final Answer
Action Input:
```

**② 模型续写产物（需正则解析）**

```text
Thought: 用户问订单状态，需调用 query_order，订单号 A1001
Action: query_order
Action Input: {"order_id": "A1001"}
```

**③ 框架拼接观察后再喂回**

```text
...（上文）
Observation: {"kind":"order_query","user_facing_summary":"订单 A1001 已发货"}
```

> 关键点：Observation 由框架拼接进 prompt，下一轮让模型续写；用正则匹配 `Action:` 后内容来路由工具，格式漂移会导致解析失败。

#### 1.5.3 两者对照速记

- 相同的「推理→行动→观察」循环，在 Function Calling 里是**结构化字段**，在 ReAct 里是**文本段落**。
- Function Calling 的「工具名 + 参数」来自 `tools` 的 JSON Schema；ReAct 的「Action + Action Input」来自 prompt 里的自由文本约定。
- ReAct 把推理链（`Thought`）天然留在可读文本里；Function Calling 需额外要求模型输出 Thought 才能看到。

---

## 2. 拓展：用 Function Calling 实现多工具并行调度

### 2.1 现状

`AgentNodeService.run` 每轮只处理模型**这一轮**返回的 `tool_calls`，但 `ToolExecutor.run` 内部是**串行**循环（`tool_executor.py:99`）：

```python
for tc in tool_calls:
    result = self._execute_one(name, args, state)   # 逐个执行
    tool_messages.append(...)
```

即：模型一次可能返回多个 `tool_calls`，但当前是「一个跑完再跑下一个」。因为同一轮里的 `tool_calls` 互不依赖（模型在同一响应里一起给出，期望全部解决后再进入下一轮推理），**它们本应可以并行**。

### 2.2 并行调度设计

核心思路：同一轮内的多个 `tool_calls` 之间没有数据依赖，用并发原语同时执行，收集全部结果后再回灌。

**线程池（同步接口，改动最小）**

把 `ToolExecutor.run` 的循环改成：

```python
from concurrent.futures import ThreadPoolExecutor

def run(self, tool_calls, state):
    with ThreadPoolExecutor(max_workers=len(tool_calls)) as pool:
        results = pool.map(
            lambda tc: self._execute_one_safe(tc, state), tool_calls
        )
    tool_messages = [self._to_tool_message(tc, r) for tc, r in zip(tool_calls, results)]
    ...
```

适合 I/O 密集型工具（`query_order` 查库、`query_logistics` 调外部 API、`rag_retrieve` 向量检索）——并发能显著压低总延迟。

**异步（asyncio，配合异步工具客户端）**

若工具客户端本身是 `awaitable`（如 `httpx.AsyncClient`、`asyncpg`），用 `asyncio.gather`：

```python
results = await asyncio.gather(*(self._execute_one_async(tc, state) for tc in tool_calls))
```

这是延迟最优解，但要求工具层全部异步化（本仓库当前是同步 `OrderService`/`LogisticsService`，需改造）。

### 2.3 依赖感知的「并行 + 串行」调度

更真实的多轮场景里，工具之间存在依赖（B 需要 A 的结果）。调度策略：

1. 第一轮：模型给出无依赖的多个 `tool_calls` → 全部并行执行；
2. 结果回灌后，模型基于观察再决定下一轮（可能又是一组可并行的 `tool_calls`）；
3. 如此逐轮推进，轮内并行、轮间串行——正是 `AgentNodeService` 的 `for _round` 循环 + 轮内并发的组合。

> 关键约束：**只有同一轮内的 `tool_calls` 可安全并行**。跨轮必须串行，因为后一轮的推理依赖前一轮的观察。

### 2.4 并行调度的注意事项

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
