# RAG 检索评测报告

> 生成时间无关；k=5，集合 `rag_eval_knowledge`，耗时 0.1s，阈值=5.0，rrf_k=60

## 策略总览

| 策略 | n | Recall@k | context_recall | context_precision | MRR |
|---|---|---|---|---|---|
| bm25 | 24 | 0.6979 | 0.9167 | 0.3333 | 0.8264 |

## 指标说明

- **Recall@k**：金标事实点（must_contain）在前 k 个召回块中的覆盖率。
- **context_recall**：金标文档（expected_doc）是否出现在前 k 个召回块（0/1 均值）。
- **context_precision**：前 k 个召回块中相关块占比（命中金标文档或含事实点）。
- **MRR**：首个命中金标文档块的排名倒数。

## 分 doc_type 明细（Recall@k）

| 策略 | doc_type | n | Recall@k | context_recall | MRR |
|---|---|---|---|---|---|
| bm25 | product | 6 | 0.5556 | 0.6667 | 0.5833 |
| bm25 | policy | 12 | 0.7569 | 1.0 | 0.9583 |
| bm25 | faq | 6 | 0.7222 | 1.0 | 0.8056 |
