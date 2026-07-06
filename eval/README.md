# Eval Assets

- `intent_single_step_cases.json`: 意图识别单点评估数据集
- `run_intent_single_step_eval.py`: 纯规则意图识别评估脚本
- `intent_single_step_results.json`: 评估结果明细
- `intent_single_step_report.md`: 评估报告
- `run_intent_compare_eval.py`: 规则-only 与 规则+LLM 对比评估
- `intent_compare_results.json`: 对比结果明细
- `intent_compare_report.md`: 对比报告

运行方式：

```bash
python3 eval/run_intent_single_step_eval.py
python3 eval/run_intent_compare_eval.py
```
