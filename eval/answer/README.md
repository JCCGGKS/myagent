# 最终回复评估（Final Answer Evaluation）

针对客服 Agent **最终回复质量**的端到端评估，仿照 LangSmith「Evaluate a complex
agent」的方法论：把评估数据集拆成 `inputs` + `reference(outputs)`，用完整
`CustomerServiceAgent` 作为 **target** 跑出预测，再用一组 **evaluator** 打分。
本仓库不依赖 `langsmith` 包，纯本地复刻其数据/目标/裁判三段式结构。

## 与 LangSmith 的对应关系

| LangSmith 概念 | 本仓库实现 |
|---|---|
| dataset example（`inputs` / `outputs`） | `answer_eval_cases.json`，见 `gen_cases.py` |
| target / prediction 函数 | `run_eval.py::run_target`（调用 `agent.chat` 跑全图） |
| LLM-as-judge evaluator | `eval_final_answer_judge`（比对理想回复 + 必含事实 + 评分要点） |
| 规则 evaluator | `eval_key_facts` / `eval_intent` / `eval_action` |
| experiment 结果落盘 | `answer_eval_results.json` + `answer_eval_report.md` |

## 数据集结构（`answer_eval_cases.json`）

```json
{
  "id": "ans_0001",
  "category": "order_query",
  "inputs":  {"message": "帮我查订单 A1001", "session_id": "ans-sess-00001"},
  "outputs": {
    "expected_main_intent": "order_query",
    "expected_sub_intent": "order_query.query_status",
    "expected_action": "agent_process",
    "expected_tool": "order_query",
    "reference_reply": "订单 A1001 当前状态为已发货……",
    "must_contain": ["A1001", "已发货", "智能客服机器人 Pro"],
    "rubric": "应准确返回订单状态、商品名称与金额，语气友好专业。"
  }
}
```

- `inputs.message`：用户问题；`session_id` 每条唯一，避免 checkpointer 跨样本串状态。
- `inputs.previous_sub_intent`：多轮跟进类样本携带，用于触发 `slot_followup` 路由。
- `outputs.reference_reply`：理想回复，供 LLM 裁判语义比对（非逐字匹配）。
- `outputs.must_contain`：确定性必含事实点，供规则评估 `key_facts` 核查。
- 覆盖五条最小闭环能力 + 问候/超出范围/投诉/澄清/多轮跟进共 11 个类别，约 1000 条。

## 评估指标

| 指标 | 类型 | 说明 |
|---|---|---|
| `key_facts` 关键事实命中率 | 规则 | reply 是否包含全部 `must_contain` |
| `intent` 意图准确率 | 规则 | 预测主/子意图 == 期望 |
| `action` 动作/轨迹准确率 | 规则 | 预测动作 == 期望；`agent_process` 时再校验工具 kind |
| `final_answer_correct` LLM 裁判通过率 | LLM-as-judge | 语义判定回复是否合格（含平均得分） |
| `latency` 响应时间 | 计时 | 单条样本 agent 产出最终回复耗时（最短/最长/平均/P50） |

## 运行

```bash
# 1) 生成数据集（约 1000 条，可重跑覆盖）
python3 eval/answer/gen_cases.py
python3 eval/answer/gen_cases.py --count 1000

# 2) 跑评估（默认全量 + LLM 裁判，结果写入 eval/answer）
python3 eval/answer/run_eval.py                      # 全量 1000 条
python3 eval/answer/run_eval.py --limit 20           # 小样本快速验证
python3 eval/answer/run_eval.py --no-llm-judge       # 仅规则评估（省 LLM 裁判调用）
python3 eval/answer/run_eval.py --max-concurrency 8  # 调并发
```

输出：
- `answer_eval_results.json`：逐条明细（预测回复/意图/动作/工具/各维度是否通过/耗时）+ 汇总指标。
- `answer_eval_report.md`：总体指标、按类别拆解、未达标样本与裁判理由。

## 已知发现（首轮评估）

- 评估暴露过 `agent_node` 把内部「无需再调工具」决策旁白当作最终回复的缺陷，
  已修复：仅当本轮循环从未调用工具（LLM 直接作答）时才写入 `state.reply`，
  调过工具后交由 `response_generator` 基于 `tool_result` 生成真正面向用户的回答
  （见 `app/business/agent/agent_node.py`）。
- 剩余主要失败模式集中在工具选择（订单类查询偶发误调 `logistics` 工具）与
  退款类意图偶发误触发 `handoff`，属 agent/LLM 行为层面问题，由评估报告持续跟踪。
