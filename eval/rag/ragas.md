# RAGAS 评测速查

RAGAS 是专门评测 RAG（检索增强生成）应用的框架。它把 RAG 拆成**检索段**与
**生成段**分别打分：检索段评 `retrieved_contexts` 的质量，生成段评 `response`
的质量。多数指标靠 **LLM-as-judge**（LLM 当裁判），少数靠 embedding 或非 LLM
字符串比对。

---

## 1. 评估数据流（Dataset）

任何 RAGAS 评估先准备样本集，每行至少含：

| 字段 | 含义 | 用途 |
|---|---|---|
| `user_input` / `question` | 用户问题 | 所有指标 |
| `response` / `answer` | RAG 生成的回答 | 生成类指标 |
| `retrieved_contexts` | 检索返回的 chunk 列表 | 检索类 + 忠实度 |
| `reference` / `ground_truth` | 人工标注标准答案 | 需真值的指标 |

> 注：当前官方文档主推 **collections-based API**（见 §5，`.ascore()` 异步逐样本打分），
> 下文方案即采用此接口以契合本项目的全异步架构。旧版 `from ragas import evaluate` +
> `Dataset` + `metrics=[...]` 的批量接口仍可用但属早期形态，新项目不建议作为主路径。

```python
from ragas.llms import llm_factory
from ragas.embeddings.base import embedding_factory
from ragas.metrics.collections import ContextRecall, ContextPrecision, Faithfulness, AnswerRelevancy

# 逐样本打分（异步，契合全异步项目）
await ContextRecall(llm=llm).ascore(
    user_input="...", reference="...", retrieved_contexts=["...", "..."])
await Faithfulness(llm=llm).ascore(
    user_input="...", response="...", retrieved_contexts=["...", "..."])
```

---

## 2. 关键指标（按评测对象分组）

### 2.1 检索质量（Context）

- **Context Recall（上下文召回率）**：标准答案里的要点，有多少被检索到的 contexts
  覆盖。**衡量漏检**。三后端差异仅在「用什么单位 + 什么方法衡量覆盖」（见 §3），语义敏感度
  LLM > 字符串 > ID，速度/确定性反向：
  - **LLM 后端（claims）**：需 `reference`。① LLM 把 `reference` 拆成若干独立 claim；
    ② 逐条判定是否可从 `retrieved_contexts` 推断（attributed=1/0）；③
    `Recall = 被支撑 claim 数 / 总 claim 数`。值域 0~1。例：金标写「Pro 支持 50 路」、
    文档写「标准版支持 50 路」→ claim 对不上 → recall=0（本评测 rag_0014 修前即此）。
  - **NonLLM 后端（字符串相似度）**：需 `reference_contexts`（金标切块文本）。用 rapidfuzz
    把每条金标块与 `retrieved_contexts` 做字符串/编辑距离比对，相似度 ≥ 阈值即算命中；
    `Recall = 命中金标块数 / 金标块总数`。零 LLM、可复现，只认字面（认不出改写）。
  - **ID 后端（块 ID 精确匹配）**：需 `reference_context_ids`（金标块 ID）+ `retrieved_ids`
    （检索返回的块携带的 doc ID）。直接取两集合交集，
    `Recall = |命中 ID 数| / |金标 ID 数|`。零 LLM、确定、最快；仅在「检索 chunk ID 能精确
    对应 gold doc ID」时最准，粒度对不上则失效。
  - 注：ContextPrecision 同理也分这三后端（LLM / 字符串 / ID），只是把「覆盖金标」换成
    「顶部块是否对答案有用」（且吃排序，见下）。
- **Context Precision（上下文精确率）**：相关 chunk 是否排在前面（看重排质量），
  用 precision@k 加权：**相关块在越靠前位置贡献越大**（位置折扣 1/i）。
  `ContextPrecision = avg over 相关位 i of (前 i 个块中相关数 / i)`，
  `i` 为该相关块在 `retrieved_contexts` 中的排名（1 起）。**衡量噪声/排序**。
  - 无关块排到第 1 位 / 相关块被挤到 #3 → 顶部全判无用、1/i 折扣使贡献骤降 →
    分数趋近 0（本评测 rag_0007 开 rerank 后 precision 1.0→0.0 即此机制）。
  - 无 `reference` 时用 **ContextUtilization**（拿 `response` 反推）。
- 其他：Context Entities Recall、Noise Sensitivity，以及 Non-LLM / ID-Based 变体。

### 2.2 生成质量（Answer）

- **Faithfulness（忠实度）**：回答是否「不胡说」——所有 claim 能否被
  `retrieved_contexts` 支撑。防幻觉核心指标。
  `Faithfulness = 被上下文支撑的 claim 数 / 回答总 claim 数`。
  - **计算步骤（LLM 后端）**：① LLM 把 `response` 拆成 statements；② 逐条判定能否
    从 `retrieved_contexts` 推断；③ 取可归因占比。值域 0~1，越高越不幻觉。
  - 可用 Vectara HHEM 小模型替代 LLM 做第二步校验（生产友好，零 API 调用）。
- **Answer/Response Relevancy（切题度）**：回答是否切题（不评对错，只评是否答到
  点上）。靠 **embedding**：**LLM 从 `response` 反推 N 个「这个问题可能是什么」的伪
  问题**，再用 embedding 把这些伪问题与原始 `user_input` 算余弦相似度，取均值。
  `Score = (1/N) Σ cos(E_gi, E_o)`。*需要 embeddings*。
  - 值域 0~1。短答案/否定句（如「不支持退款」「标准版支持 50 路」）生成的伪问题弱，
    容易偏低；答案讲的对象与问题不一致（如答案讲「标准版」、问题问「Pro 版」）→
    语义不匹配 → 趋近 0（本评测 rag_0014）。
- **Answer Correctness**：需 `reference`。
- Nvidia 三件套：Answer Accuracy / Context Relevance / Response Groundedness。

---

## 3. 三种覆盖计算口径（核心）

检索类指标（Precision/Recall）在每个指标下都有三种实现，区别只在
**「用什么单位 + 什么方法衡量覆盖」**，语义敏感度 `1 > 2 > 3`：

| 口径 | 怎么算 | 需要输入 | 语义敏感度 | 速度/成本/确定性 |
|---|---|---|---|---|
| **1. LLM（claims）** | LLM 把 reference 拆 claim，逐条判断被 context 覆盖多少 | `reference`（或 `response` 做无参考版）+ LLM | 高（认改写） | 慢、贵、有随机 |
| **2. 字符串** | 字符串相似度（rapidfuzz/Levenshtein）比对 chunk 与 `reference_contexts` | `reference_contexts` + `pip install rapidfuzz` | 低（只认字面） | 快、便宜、确定 |
| **3. ID** | 直接比对检索 doc ID 与标准 doc ID 集合 | `retrieved_context_ids` + `reference_context_ids` | 无（精确匹配） | 最快、零成本、确定 |

> 反向维度：`3 > 2 > 1`（速度/成本/确定性递增）。
> 反例：若知识库有**完美稳定的 ID 体系**（检索 chunk ID 能精确对应 gold doc ID），
> ID 版反而最准（零 fuzzy 误判）。它「不准」只发生在 ID 粒度对不上时。

对应 RAGAS 类：
- Context Recall → `ContextRecall` / `NonLLMContextRecall` / `IDBasedContextRecall`
- Context Precision → `ContextPrecision` / `NonLLMContextPrecision*` / `IDBasedContextPrecision`

---

## 4. reference 与 claim

- **reference**：人工标注的标准答案（ground truth），衡量「离标准还差多少」。
  用于需真值的指标（Context Recall、Context Precision with reference、Answer Correctness）。
- **claim**：一句话里可被独立验证的**最小事实单元**，由 LLM 从文本拆出，是比对的
  最小颗粒度。整句对整句太死板（措辞不同就判错），claim 让「半对」可量化。
- 配合（Context Recall）：reference 拆 claim → 逐条判断是否被 `retrieved_contexts`
  支撑 → `Recall = 被支撑 claim 数 / 总 claim 数`。
- `claim` 不仅用于 reference：**Faithfulness** 也把生成的 `response` 拆 claim，再判
  每个 claim 是否被 `retrieved_contexts` 支撑。claim 是「生成侧」与「标准侧」共用单位。

---

## 5. 两种 API 风格

文档主推 **collections-based API**（旧版 0.4 弃用、1.0 移除）：

```python
from openai import AsyncOpenAI
from ragas.llms import llm_factory
from ragas.embeddings.base import embedding_factory
from ragas.metrics.collections import ContextRecall, Faithfulness, AnswerRelevancy

llm = llm_factory("gpt-4o-mini", client=AsyncOpenAI())
emb = embedding_factory("openai", model="text-embedding-3-small", client=...)

await ContextRecall(llm=llm).ascore(
    user_input="...", reference="...", retrieved_contexts=[...])      # 检索
await Faithfulness(llm=llm).ascore(
    user_input="...", response="...", retrieved_contexts=[...])       # 生成
await AnswerRelevancy(llm=llm, embeddings=emb).ascore(
    user_input="...", response="...")                                # 切题
```
- 异步 `.ascore()`，同步 `.score()`。
- 旧版：`from ragas.metrics import LLMContextRecall` + `SingleTurnSample` +
  `.single_turn_ascore(sample)`，新项目勿用。

---

## 6. 本仓库调用装配（eval/rag/run_ragas_eval.py）

评测脚本用 collections-based 异步 API，在 `judge()` 内一次性产出全部指标：

```python
# 检索段（白盒）—— 三种后端可选，由 --retrieval-backend 控制
_llm()    → ContextRecall(llm) + ContextPrecision(llm)        # 语义 claims
_nonllm() → NonLLMContextRecall + NonLLMContextPrecisionWithReference  # 字符串相似度
_id()     → IDBasedContextRecall + IDBasedContextPrecision    # 块 ID 匹配
# 生成段（黑盒）—— 仅 LLM 后端，无 nonllm/id 变体
Faithfulness(llm).ascore(user_input, response, retrieved_contexts)
AnswerRelevancy(llm, embeddings).ascore(user_input, response)
```

- `--retrieval-backend all` 跑全部三种后端；`llm` 只跑 LLM 后端（report_02~06 口径）。
- 所有 LLM 裁判调用走打过补丁的 `AsyncOpenAI` 客户端（`_patch_thinking_off` 强制
  `enable_thinking=False`，规避网关 400/超时）；judge 与生成共用 `qwen3.7-plus`。
- 生成段指标**只有 LLM 后端**，不存在 nonllm/id 变体（见 §3）。
- 指标分工速记：召回/精确率评「检索到的块」对不对、全不全（白盒，吃 `retrieved_contexts`，
  精确率额外吃**排序**、位置权重 1/i）；忠实度/相关性评「生成的答案」编没编、切没切题
  （黑盒，吃 `response`；相关性靠「从答案反推问题再比原问题」的 embedding 相似度）。
