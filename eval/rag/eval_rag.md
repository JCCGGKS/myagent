# eval/rag 评测方案（RAGAS 直评，无独立白盒 harness）

本文件是 `eval/rag` 的**唯一评测方案**：直接用 RAGAS 评测本项目 RAG，**不再保留独立的白盒
确定性 harness**（`run_eval.py` 的指标计算部分已弃用，其入库/检索辅助逻辑可被本方案复用）。
RAGAS 工具速查见 `ragas.md`。

---

## 1. 为什么需要专门的 RAG 评测

几个样例对比无法全面衡量 RAG 回答质量，需要**可信、可复现的指标**定量迭代。
本仓库已建 `intent` / `trajectory` / `answer` 三套评估（见 `eval/eval.md`）。答案评估基线
暴露的残余缺口是：

> 退款政策 `consult_policy` 已正确选 `rag_retrieve`，但**检索返回弱/空**，回复缺
> 「七天无理由 / 原路退回」等事实点。

即问题出在**检索层**与**生成层**，本方案用 RAGAS 一次性把两层都量化。

---

## 2. RAGAS 一次覆盖检索 + 生成（黑白盒同跑）

**澄清：RAGAS 一套指标同时覆盖黑白盒，不是「只做黑盒」或「二选一」。**

- `ContextRecall` / `ContextPrecision` 吃 `retrieved_contexts` → 评**检索组件**（白盒层）。
- `Faithfulness` / `AnswerRelevancy` / `AnswerCorrectness` 吃 `response` → 评**生成答案**（黑盒层）。
- **一次 RAGAS 运行同时产出检索段 + 生成段分数**，无需拆成两条链路、也无需单独的确定性 harness。

因此本方案**只用 RAGAS**：检索质量的「便宜/可复现」需求，由 RAGAS 自带的 Non-LLM / ID
计算后端满足（见 §3），不必另写一套子串/块计数的白盒脚本。

---

## 3. 指标（按评测对象组织）

> **纠正常见误解**：RAGAS 不是「LLM / Non-LLM / ID 三种方案」构成的框架。RAGAS 按**指标**
> 组织；`LLM / Non-LLM / ID` 只是**部分检索指标提供的多种计算后端**，是 implementation
> detail，不是框架架构。生成指标只有 LLM 后端，根本不存在 Non-LLM / ID 变体。

### 3.1 检索段（吃 `retrieved_contexts`）

| 指标 | 计算后端 | 必需输入 | 说明 |
|---|---|---|---|
| `ContextRecall` | LLM（拆 claim 语义比对） | `reference` | 语义召回上限 |
| `ContextRecall` | Non-LLM（rapidfuzz 相似度） | `reference_contexts` | 零 LLM、可复现 |
| `ContextRecall` | ID（doc-id 比对） | `reference_context_ids` | 零 LLM、确定、需文档 ID 体系 |
| `ContextPrecision` | LLM / Non-LLM / ID | 同上对应 | 加权 precision@k（×相关位 vₖ） |
| `Context Entities Recall` | LLM | `reference` | 实体级召回 |
| `Noise Sensitivity` | LLM | `reference` + 加噪上下文 | 抗噪能力 |

> 检索段三种后端（LLM / Non-LLM / ID）只存在于 `ContextRecall` / `ContextPrecision`
> （及其实体/噪声变体）。想「便宜可复现」就选 Non-LLM 或 ID 后端——**这就是替代原白盒
> harness 的等价能力**，无需独立脚本。

### 3.2 生成段（吃 `response`，仅 LLM 后端）

| 指标 | 必需输入 | 说明 |
|---|---|---|
| `Faithfulness` | `user_input` + `response` + `retrieved_contexts` | **防幻觉核心** |
| `AnswerRelevancy` | `user_input` + `response` + **embeddings** | 切题度，需 embedding 端点 |
| `AnswerCorrectness`（可选） | `response` + `reference` | 需 `reference` |

---

## 4. 数据集

基于 `rag_eval_cases.json`（24 条，md/ 8 篇）。每条 case = 用户问法 + 金标：

```json
{
  "id": "rag_0001",
  "query": "钱什么时候退回来",
  "expected_doc": "md/refund_policy.md",
  "doc_type": "policy",
  "reference": "退款将原路退回，到账时间以支付渠道为准。",
  "reference_contexts": ["退款将原路退回……", "到账时间以支付渠道为准……"],
  "reference_context_ids": ["doc_refund_policy_3", "doc_refund_policy_7"]
}
```

- `query` / `expected_doc`：供检索调用与 ID 后端定位金标文档。
- `reference`（**完整自然语言标准答案**，非事实点列表）：LLM 后端 `ContextRecall` /
  `ContextPrecision` / `AnswerCorrectness`。
- `reference_contexts`（金标文档切块文本）：Non-LLM 后端。
- `reference_context_ids`（金标文档/块 ID）：ID 后端；要求检索返回的 chunk 携带稳定 doc ID。
- 生成方式：离线从 `expected_doc` 截取含事实点的段落拼接（确定性、推荐），或 LLM 合成。

基于 `template/knowledge/md/` 8 篇结构化文档构造金标（设计要点见 `md/README.md`）：

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

`pdf/` `ppt/` `word/` `qa/` `json/` `excel_csv/` 多格式样本不纳入主评测集，留作跨格式专项测试。

---

## 5. 被测对象（绕过整图，真实链路）

- **检索**：直接调 `RagRetrieveTool.run` / `get_strategy_from_config`，分别开关 `bm25` /
  `semantic` / `hybrid` 三策略（见 `app/business/rag/retrieval_strategy.py`），取
  `retrieved_contexts`（带 `metadata` 中的 doc ID，供 ID 后端用）。
- **生成**：用项目 LLM 网关对 (query + contexts) 真实生成 `response`，供生成段指标。

---

## 6. 评估器（RAGAS 单一）

用 collections-based 异步 API（契合全异步架构），一次运行同时产出检索段 + 生成段：

```python
from openai import AsyncOpenAI
from ragas.llms import llm_factory
from ragas.embeddings.base import embedding_factory
from ragas.metrics.collections import (
    ContextRecall, ContextPrecision, Faithfulness, AnswerRelevancy,
)
from app.config.llm import load_llm_config

cfg = load_llm_config()
client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
llm = llm_factory(cfg.model, client=client)
emb = embedding_factory("openai", model="text-embedding-3-small", client=client)

# 检索段（白盒）—— 后端可选 llm / nonllm / id
await ContextRecall(llm=llm).ascore(
    user_input=q, reference=ref, retrieved_contexts=ctxs)          # LLM 后端
# NonLLMContextRecall(reference_contexts=...) / IDBasedContextRecall(reference_context_ids=...)
# 生成段（黑盒）—— 仅 LLM 后端
await Faithfulness(llm=llm).ascore(
    user_input=q, response=ans, retrieved_contexts=ctxs)
await AnswerRelevancy(llm=llm, embeddings=emb).ascore(
    user_input=q, response=ans)
```

- **快速回归**：选 Non-LLM 或 ID 后端跑 `ContextRecall`/`ContextPrecision`，零 LLM、秒级、
  可复现，等价于原白盒 harness 的检索质量检查。
- **语义/质量审计**：选 LLM 后端跑检索段 + 生成段（`Faithfulness` 必做），得到贴近人类的
  召回分与幻觉率。
- 生成段必须接真实 `response`，否则 `Faithfulness` / `AnswerRelevancy` 无输入。

---

## 7. 运行方式

```bash
# 数据集（补 reference / reference_contexts / reference_context_ids）
python3 eval/rag/gen_cases.py --with-reference

# RAGAS 直评（端到端黑白盒同跑）
python3 eval/rag/run_ragas_eval.py                       # 三策略 + 检索段(LLM) + 生成段
python3 eval/rag/run_ragas_eval.py --retrieval-backend id,nonllm   # 仅零 LLM 后端（快、回归用）
python3 eval/rag/run_ragas_eval.py --strategies bm25     # 仅 BM25
python3 eval/rag/run_ragas_eval.py --no-ingest           # 复用已入库数据
```

- 脚本把 `template/knowledge/md/` 入库到独立评测集合 `rag_eval_knowledge`（复用原
  `run_eval.py` 的入库/检索辅助逻辑），不污染生产集合；semantic / hybrid 需配顶层 `embedding`。
- 依赖：`pip install ragas`（`requirements.txt` 当前不含）；judge 用项目 LLM 网关；
  `AnswerRelevancy` 需可达 embedding 端点。

---

## 8. 项目特有正确性约束（务必遵守）

1. **LLM 裁判必须关闭 thinking**：项目网关有 thinking-mode 约束（qwen3.7-max 需显式
   `enable_thinking=false`；preview / 05-17 强制 thinking 会 400）。RAGAS 内部多次调 LLM
   当裁判，不关 thinking 必超时/报错。**落地第一坑。**
2. **Embeddings 端点**：`AnswerRelevancy` 需 OpenAI 兼容 embeddings 接口；若项目 embedding
   网关兼容则复用，否则该指标可省（检索段 + Faithfulness 已覆盖主线）。
3. **`reference` 是完整答案，不是事实点列表**；`reference_contexts` / `reference_context_ids`
   按所选后端提供。
4. **策略配置**：沿用三策略初始值（见 §9），换策略必须换 `min_score_threshold` 量纲。

---

## 9. 三策略初始配置（评估起点）

跑完后用检索段指标定 `top_k`、收紧 `min_score_threshold` 迭代。

| 参数 | bm25 | semantic | hybrid |
|---|---|---|---|
| `retrieval_strategy` | `bm25` | `semantic` | `hybrid` |
| `top_k` | `5` | `5` | `6` |
| `min_score_threshold` | `4` | `0.0` | `0.0` |
| `chunk_size` / `overlap` / `min_chunk_size` | `800` / `100` / `50` | 同 | 同 |
| `rrf_k` | `60` | `60` | `60` |
| `rerank.enabled` | 关（可选） | 开（建议） | **开（建议）** |
| 依赖 | 无 | 需顶层 `embedding` | 需顶层 `embedding` |

三条硬规则：① 阈值量纲 bm25 `0~10`（初始 4）、semantic `0~1`（初始 0.0）、hybrid RRF（必须 0.0），
  跨策略直套会返回空结果；② semantic/hybrid 前置校验 `embedding.api_key`；③ rerank 是精度调节点。

---

## 10. 实施优先级

1. **快速回归（零 LLM）**：Non-LLM / ID 后端跑 `ContextRecall`/`ContextPrecision`，先确认
   检索器基线无误（等价于原白盒 harness 的检索质量检查，但走 RAGAS 统一接口）。
2. **语义检索审计（LLM）**：LLM 后端 `ContextRecall`/`ContextPrecision` 拿真实语义召回，
   量化子串/ID 口径的差距。
3. **生成端到端（LLM）**：接通 `response` 生成，跑 `Faithfulness`（防幻觉，必做）+
   `AnswerRelevancy`（切题），输出最终回答质量与幻觉率结论。
```
