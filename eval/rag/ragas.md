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
  覆盖。*必须*有 `reference`（把 reference 拆成 claim，逐条判断是否被 contexts 支撑）。
  `Recall = 被支撑的 claim 数 / reference 总 claim 数`。**衡量漏检**。
- **Context Precision（上下文精确率）**：相关 chunk 是否排在前面（看重排质量），
  用 precision@k 加权：`Precision@K = Σ(Precision@k × vₖ) / 相关项总数`，
  `vₖ` 为第 k 位相关性 0/1。**衡量噪声/排序**。无关块若排到第 1 位，分数明显下掉。
  - 无 `reference` 时用 **ContextUtilization**（拿 `response` 反推）。
- 其他：Context Entities Recall、Noise Sensitivity，以及 Non-LLM / ID-Based 变体。

### 2.2 生成质量（Answer）

- **Faithfulness（忠实度）**：回答是否「不胡说」——所有 claim 能否被
  `retrieved_contexts` 支撑。防幻觉核心指标。
  `Faithfulness = 被上下文支撑的 claim 数 / 回答总 claim 数`。
  可用 Vectara HHEM 小模型替代 LLM 做第二步校验（生产友好，零 API 调用）。
- **Answer/Response Relevancy（切题度）**：回答是否切题（不评对错，只评是否答到
  点上）。靠 **embedding**：LLM 从回答反推 N 个问题，算其与原始问题的余弦相似度均值。
  `Score = (1/N) Σ cos(E_gi, E_o)`。*需要 embeddings*。
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
