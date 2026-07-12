# Eval 评估套件

## 文件说明

| 文件 | 作用 |
|---|---|
| `run_eval.py` | 统一评估入口脚本，三种模式共用 |
| `gen_cases.py` | **测试集生成器**：对齐当前生产意图空间，重新生成 `intent_single_step_cases.json` |
| `intent_single_step_cases.json` | 评估数据集（约 1000 条，由 `gen_cases.py` 生成，**勿手改**） |
| `intent_single_step_results_no_llm.json` | 规则-only 原始结果（程序可读） |
| `intent_single_step_report_no_llm.md` | 规则-only 可读报告 |
| `intent_single_step_results_with_llm.json` | 规则+LLM 原始结果 |
| `intent_single_step_report_with_llm.md` | 规则+LLM 可读报告 |
| `intent_compare_results.json` | 对比结果中间文件 |
| `intent_compare_report.md` | **对比报告（最终输出，人可读）** |

> 金标（expected）严格对齐 `app/schema/intent.py` 的 `MAIN_INTENT_CODES` / `SUB_INTENT_CODES`。
> 早期手写数据集引用了已废弃的子意图（如 `chitchat.greeting`、`logistics.delayed` 当作规则产出），
> 与当前路由层不一致，已通过 `gen_cases.py` 重新生成。

## 快速开始

```bash
# 1) 重新生成测试集（对齐当前意图空间）
python3 eval/intent/gen_cases.py --count 1000

# 2) 完整流程：规则-only + 规则+LLM + 对比报告
python3 eval/run_eval.py

# 仅生成对比报告（读取已有结果，不重复推理）
python3 eval/run_eval.py --compare-only

# 仅跑规则-only
python3 eval/run_eval.py --no-llm

# 仅跑规则+LLM
python3 eval/run_eval.py --with-llm
```

## 测试集构成（gen_cases.py）

生成器覆盖五类样本，使「规则-only vs 规则+LLM」对比有真实差异：

- `rule_hit`（规则关键词直接命中，两者都应命中）
- `finer_subintent`（规则只给粗子意图 / action-only 短语规则不命中，仅 +LLM 能给出细子意图）
- `colloquial`（口语/省略表达，无规则关键词，需 LLM 兜底）
- `multiturn_followup`（带 `previous_sub_intent` 的多轮跟进）
- `unrecognize`（问候 / 超出业务范围）

单轮格式：

```json
{
  "id": "case_0001",
  "message": "查订单",
  "expected_main_intent": "order_query",
  "expected_sub_intent": "order_query.query_status",
  "category": "rule_hit"
}
```

多轮追问加 `previous_sub_intent`：

```json
{
  "id": "followup_0001",
  "message": "A1001",
  "previous_sub_intent": "order_query.query_status",
  "expected_main_intent": "order_query",
  "expected_sub_intent": "order_query.query_status",
  "category": "multiturn_followup"
}
```

## 评估逻辑

`run_eval.py` 直接调用 `IntentRouterService.route()`，与生产代码路径一致，避免之前两个独立脚本各自实现路由导致结果不一致的问题。

对比报告会输出：
- 规则-only 准确率
- 规则+LLM 准确率
- LLM 兜底命中次数
- 准确率提升幅度
