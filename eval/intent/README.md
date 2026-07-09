# Eval 评估套件

## 文件说明

| 文件 | 作用 |
|---|---|
| `run_eval.py` | 统一评估入口脚本，三种模式共用 |
| `intent_single_step_cases.json` | 评估数据集（1000 条样本） |
| `intent_single_step_results_no_llm.json` | 规则-only 原始结果（程序可读） |
| `intent_single_step_report_no_llm.md` | 规则-only 可读报告 |
| `intent_single_step_results_with_llm.json` | 规则+LLM 原始结果 |
| `intent_single_step_report_with_llm.md` | 规则+LLM 可读报告 |
| `intent_compare_results.json` | 对比结果中间文件 |
| `intent_compare_report.md` | **对比报告（最终输出，人可读）** |

## 快速开始

```bash
# 完整流程：规则-only + 规则+LLM + 对比报告
python3 eval/run_eval.py

# 仅生成对比报告（读取已有结果，不重复推理）
python3 eval/run_eval.py --compare-only

# 仅跑规则-only
python3 eval/run_eval.py --no-llm

# 仅跑规则+LLM
python3 eval/run_eval.py --with-llm
```

## 添加样本

直接编辑 `intent_single_step_cases.json`，单轮格式：

```json
{
  "id": "case_0001",
  "message": "查订单",
  "expected_main_intent": "order_query",
  "expected_sub_intent": "order_query.query_status"
}
```

多轮追问加 `previous_sub_intent`：

```json
{
  "id": "followup_0001",
  "message": "A1001",
  "previous_sub_intent": "order_query.query_status",
  "expected_main_intent": "order_query",
  "expected_sub_intent": "order_query.query_status"
}
```

## 评估逻辑

`run_eval.py` 直接调用 `IntentRouterService.route()`，与生产代码路径一致，避免之前两个独立脚本各自实现路由导致结果不一致的问题。

对比报告会输出：
- 规则-only 准确率
- 规则+LLM 准确率
- LLM 兜底命中次数
- 准确率提升幅度
