# RAG 评测基础知识（eval/rag）

本文件沉淀 RAG 评测的通用方法论，并将其映射到本仓库 `eval/` 的分层评估体系，
作为 `eval/rag` 评测 harness 的设计依据。内容综合自 Zilliz《RAG 修炼手册｜如何评估
RAG 应用？》，并结合本仓库 `app/business/rag`（分块→向量化→入库→检索→融合→重排）
的落地实现。

---

## 1. 为什么需要专门的 RAG 评测

几个样例对比无法全面衡量 RAG 回答质量，需要**可信、可复现的指标**定量迭代。
本仓库已建 `intent`（组件级意图）/ `trajectory`（流程级路径）/ `answer`（结果级回复）
三套评估（见 `eval/eval.md`）。答案评估基线暴露的残余缺口是：

> 退款政策 `consult_policy` 已正确选 `rag_retrieve`，但**检索返回弱/空**，回复缺
> 「七天无理由 / 原路退回」等事实点。

即问题出在**检索层**，`eval/rag` 负责把这层下钻量化。

---

## 2. 评测视角：黑盒 vs 白盒

| 视角 | 能看到什么 | 评估对象 | 适用 |
|---|---|---|---|
| 黑盒 | 仅 query / retrieved contexts / response 三元组 | 端到端（含 LLM 生成） | 闭源 / 整体回答质量 |
| 白盒 | 内部 pipeline（embedding / rerank / 多路召回） | 单个组件 | 开源 / 自研 RAG 调参 |

本仓库 `eval/rag` 以**白盒检索层**为主（直接调 `RagRetrieveTool` / `HybridStrategy`），
不跑整图、不调 LLM 生成；黑盒的生成质量已由 `eval/answer` 覆盖。

---

## 3. 黑盒指标（三元组两两相关度，LLM-as-judge）

无需 ground-truth，用强 LLM（如 GPT-4，与人类约 80% 一致）按 prompt 自动打分：

- **Context Relevance（上下文相关性）**：召回的 context 是否能支撑 query。低 → 召入
  过多无关内容，带偏 LLM。
- **Faithfulness（忠实度）**：答案是否在给定的 context 内事实一致。低 → 幻觉风险大。
- **Answer Relevance（答案相关性）**：答案是否切题、完整、无冗余。
- 有 ground-truth 时增加 **Answer Correctness**（答案正确性）。

无标注数据时，可让 LLM 基于知识文档**合成 query + 标准答案 + context 出处**
（ragas Synthetic Test Data / llama-index QuestionGeneration 已集成），从而评估私有数据集。

> 映射：Context Relevance / Faithfulness / Answer Correctness 对应本仓库
> `eval/answer` 的 `final_answer_correct`（LLM 裁判），属黑盒，不在 `eval/rag` 重复实现。

---

## 4. 白盒指标（检索召回层，确定性、需 ground-truth contexts）

这是 `eval/rag` 的核心。给 query 配期望召回的金标 context / 事实点，用确定性指标计算，
**快、便宜、可复现**，适合反复调 `chunk_size` / `rrf_k` / `top_k` / `retrieval_strategy`。

### 4.1 不看排名（set-based）
- **Context Recall（上下文召回率）**：是否完整召回了所有必要文档/块。
- **Context Precision（上下文精确率）**：召回结果中相关块占比（噪声多少）。

### 4.2 看排名（ranking-based）
- **MRR（Mean Reciprocal Rank）**：第一个相关块排名的倒数均值。
- **MAP（Mean Average Precision）**：所有相关块加权精度均值。
- **NDCG**：相关性为非二元（分级）时的排名质量。

### 4.3 模型选型公开 benchmark
- **MTEB**：embedding 模型重点看 NDCG，rerank 模型重点看 MAP。
- 注意公开数据集可能过拟合，最终以**业务自定义数据集**上的指标为准。

---

## 5. 与本仓库 eval 体系的映射

| 文章指标（层） | 本仓库落点 | 说明 |
|---|---|---|
| Context Recall / Precision（白盒检索） | **`eval/rag`**（新增） | 金标事实点是否在 top_k、噪声多不多 |
| MRR / MAP / NDCG（白盒检索） | **`eval/rag`**（新增） | RRF 融合后金标文档排名质量 |
| Context Relevance（黑盒） | `eval/rag` 可选增强 | LLM 裁判召回是否支撑 query |
| Faithfulness（黑盒） | `eval/answer.final_answer_correct` | 跨层复用，不重造 |
| Answer Relevance / Correctness（黑盒） | `eval/answer` | 已有 |

---

## 6. eval/rag harness 设计（待实现）

### 6.1 数据集 `rag_eval_cases.json`
每条 case = 一个用户问法 + 金标（期望命中文档 + 必含事实点）：

```json
{
  "id": "rag_0001",
  "query": "钱什么时候退回来",
  "expected_doc": "md/refund_policy.md",
  "doc_type": "policy",
  "must_contain": ["原路退回", "到账时间以支付渠道为准"]
}
```

#### 评测语料：`template/knowledge/md/`

`eval/rag` 基于 `template/knowledge/md/` 下**结构化 Markdown 文档**构造金标：

| 路径 | doc_type | 主题 | 关键事实点（金标） |
|---|---|---|---|
| `md/refund_policy.md` | policy | 退款政策 | 七天无理由退货退款 / 原路退回 / 到账时间以支付渠道为准 |
| `md/after_sale.md` | policy | 售后与退换货流程 | 退换货 5 步流程 / 质量问题免运费 / 质保一年（整机一年、主要部件两年） |
| `md/logistics_shipping.md` | policy | 物流配送规则 | 满 99 包邮 / 基础运费 8 元 / 跨省 3-5 天 / 物流停滞 72h 催查 |
| `md/order_faq.md` | faq | 订单常见问题 | 修改地址（未发货前）/ 取消订单状态区分 / 订单状态说明 |
| `md/invoice_rule.md` | policy | 发票规则 | 电子普票 / 增值专票（需税号）/ 已发货或已完成才可开票 |
| `md/product_robot_pro.md` | product | 智能客服机器人 Pro | 售价 1999 / 50 路并发 / 整机一年质保 |
| `md/product_kb_pack.md` | product | 知识库增强包 | 售价 399 / 依赖 Pro 版 / 虚拟服务激活后不支持无理由退款 |
| `md/membership_faq.md` | faq | 会员与账户 FAQ | 三档会员 / 转人工创建服务单 / 优惠不折现 |

`md/README.md` 记录这 8 篇的设计要点（覆盖场景、与 `eval/answer` 对齐、标题切块、
难度梯度），均为评测设计依据。`template/knowledge/` 下的 `pdf/` `ppt/` `word/` `qa/`
`json/` `excel_csv/` 多格式样本不纳入主评测集，留作后续跨格式入库/检索专项测试。

### 6.2 被测对象（白盒，绕过整图）
直接调 `RagRetrieveTool.run` 或 `get_strategy_from_config`，分别开关
`bm25` / `semantic` / `hybrid` 三策略对比（见 `app/business/rag/retrieval_strategy.py`）。

### 6.3 评估器
- `Recall@k`：金标事实点是否进入 top_k（k 取 `rag.top_k`）；即前 k 个召回块中覆盖了多少必含事实点，按文档召回率口径计算。
- `context_recall`：金标文档/块是否被召回。
- `context_precision`：召回块中相关块占比。
- `mrr`：首个金标块排名倒数。
- （可选）`context_relevance`：LLM 裁判。

### 6.4 运行方式

```bash
# 数据集（24 条，md/ 8 篇文档）
python3 eval/rag/gen_cases.py

# 评测（需 Qdrant 在线）
python3 eval/rag/run_eval.py                        # bm25 / semantic / hybrid（可行时）
python3 eval/rag/run_eval.py --strategies bm25     # 仅 BM25（无需 embedding）
python3 eval/rag/run_eval.py --k 3 --limit 10      # 自定义 k 与样本数
python3 eval/rag/run_eval.py --no-ingest           # 复用已入库数据
```

- 脚本把 `template/knowledge/md/` 入库到**独立评测集合** `rag_eval_knowledge`，不污染
  生产集合；每次运行默认重置该集合后重新入库。
- semantic / hybrid 需要配置顶层 `embedding`（api_key）；未配置时脚本自动跳过，仅跑 bm25。
- 金标事实点（`must_contain`）必须是文档**逐字子串**，否则 `Recall@k` 的子串判定会失真
  （早期版本用释义摘要作金标，导致 `Recall@k` 被严重低估，已修正）。

### 6.5 基线（已验证，BM25-only）

当前环境未配置 embedding，仅可跑 BM25（24 条 case，k=5，阈值=5.0，rrf_k=60）：

| 策略 | n | Recall@5 | context_recall | context_precision | MRR |
|---|---|---|---|---|---|
| bm25 | 24 | 0.6979 | 0.9167 | 0.3333 | 0.8264 |

解读：
- **context_recall 0.92 / MRR 0.83**：BM25 基本能召回正确文档，且排在前部；
- **Recall@5 0.70**：约 30% 的金标事实片段未进入 top-5（多因长文档切块后事实块排名靠后，
  如 product 类仅 0.56）；
- **context_precision 0.33**：top-5 中仅 1/3 为相关块——BM25 跨文档噪声明显，正是
  hybrid / rerank 应改善的方向。

配置 embedding 后跑 `semantic` / `hybrid` 即可对比排名与精度提升。

---

## 7. 工具生态（参考，非必须）

Ragas / TruLens-Eval / DeepEval / Continuous-eval / LangSmith / OpenAI Evals。
本仓库优先用自研白盒确定性指标（零 LLM 调用、便宜可复现），工具类作为可选增强。

---

## 8. 实施优先级建议

1. **先做白盒确定性部分**：query 集（从 README 金标自动生成）+ Recall/Precision/MRR
   + hybrid/bm25/semantic 三策略对比。这是调参最高频、最便宜的部分。
2. **LLM 裁判类**（Context Relevance / Faithfulness）作为可选增强，且 Faithfulness
   已被 `eval/answer` 覆盖，避免重复。
