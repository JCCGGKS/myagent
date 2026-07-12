# 客服 Agent 评估体系

本仓库对客服 Agent（`CustomerServiceAgent`，LangGraph 编排）建立三套互补评估，
覆盖运行链路的三个层次：

| 层级 | 评估 | 目录 | 被测对象 |
|---|---|---|---|
| 组件级 | 单点（意图识别） | `eval/intent` | 仅 `IntentRouterService` |
| 流程级 | 轨迹（决策路径） | `eval/trajectory` | 整图 `graph.astream` |
| 结果级 | 答案（最终回复） | `eval/answer` | 整图 `agent.chat` |

三者**共享同一消息分布**（答案评估用 `gen_cases.py` 生成 1000 条，轨迹评估
复用相同 seed 与消息），因此结果可直接横向对比。方法论仿照 LangSmith
「Evaluate a complex agent」：dataset（`inputs` / `outputs=reference`）→ target
（预测函数）→ evaluators（打分）→ experiment（指标 + 报告）。

---

## 1. 单点评估（意图识别）— `eval/intent`

**评估什么**：链路最前端「意图识别」这一个环节对不对。给一句话，看
`IntentRouterService` 是否把**主意图 + 子意图**识别正确。不跑工具、不生成回复。

**怎么评估**：
- 直接调用 `IntentRouterService.route(state, message)`（绕过整个 LangGraph），属「组件级」单步测试；
- 每条 case 比对 `actual.main_intent/sub_intent == expected`，命中即算对；
- 指标：整体准确率、按主意图拆解的准确率、`route_source` 分布（规则命中 / 上下文跟进 / LLM 兜底 / 未识别）；
- 支持「纯规则」与「规则 + LLM 兜底」两种模式对比，并可扫描 LLM 覆盖阈值（confidence < T 时改用 LLM 覆盖）找最优 T；
- 全部规则判定，确定性、极快。

**产物**：`intent_single_step_cases.json` / `intent_single_step_results_*.json` /
`intent_single_step_report_*.md`，以及对比报告 `intent_compare_report.md`。

---

## 2. 轨迹评估（决策路径）— `eval/trajectory`

**评估什么**：agent 在 LangGraph 里**走的对不对**——执行了哪些节点、走了哪个分支、
槽位/缺失槽位是否正确、该澄清时是否澄清、工具 kind 是否选对。关心**路径与决策**，
不关心最终那段文字写得好不好。

**数据集金标**（`trajectory_eval_cases.json`，在 answer 样本上追加）：
- `expected_node_path`：期望执行的节点序列（BASE + 动作分支 + `context_compressor`）；
- `expected_reply_source_node`：最终回复产出节点（`clarification_node` / `response_generator`）；
- `expected_order_id`：消息中应由 `state.slots` 抽出的订单号；
- `expected_missing_slots`：期望缺失槽位（意图需订单号且消息无单号 → `["order_id"]`）；
- `expected_needs_clarification`：是否应进入澄清。

节点路径映射（与 `app/business/agent/graph.py` 一致）：

| 期望动作 | 期望节点路径 |
|---|---|
| `agent_process` | input_normalizer → intent_router → state_tracker → policy_layer → **agent_node** → response_generator → context_compressor |
| `handoff_human` | … → **handoff_node** → response_generator → context_compressor |
| `ask_intent_clarification` / `ask_slot_clarification` | … → **clarification_node** → context_compressor |
| `answer_directly` | … → response_generator → context_compressor |

**怎么评估**：
- 用 `graph.astream` 跑全图，逐节点捕获 `node_order` + `intent` + `slots/missing_slots` + `action` + `tool_kind` + `reply_source_node`；
- 6 个确定性规则评估器（无需 LLM 裁判）：
  - `route_correct`：实际节点序列 == 期望序列（含分支与 context_compressor）；
  - `intent_correct`：主/子意图 == 期望；
  - `action_correct`：动作 == 期望；`agent_process` 时再校验工具 kind；
  - `slot_extraction_correct`：消息有订单号时 `state.slots` 正确抽出；
  - `missing_slot_correct`：缺失槽位 == 期望；
  - `clarification_correct`：`needs_clarification` 与期望一致，且澄清类回复确实追问了订单号；
  - `trajectory_overall` = 上述六项全过（端到端走对路径）；
- 含响应时间统计（min / max / avg / P50，单条样本跑完整图耗时，含工具调用）。

**产物**：`trajectory_eval_cases.json` / `trajectory_eval_results.json` / `trajectory_eval_report.md`。

> 全量 1000 条结果（规则评估，无 LLM 裁判）：
> - 节点路径 98.90%、意图 88.20%、动作/分支 **66.50%**、槽位抽取 100%、缺失槽位 100%、澄清 99.40%
> - **轨迹总准确率（六项全过）61.10%**
> - 响应时间：最短 0.676s / 最长 49.831s / 平均 6.280s / P50 5.295s
> - 动作失配是总准确率的主要拖累，根因是 **agent_node 误选工具 kind**：
>   订单查询调 `logistics`、物流查询调 `order_query`、退款类频繁调 `handoff`/`knowledge`
>   而非 `aftersale_refund`。路径本身几乎全对（98.90%），说明编排骨架正确，问题集中在
>   ReAct 工具选择这一环。

---

## 3. 答案评估（最终回复）— `eval/answer`

**评估什么**：最终发给用户的那句话**好不好**——关键事实是否到位、意图/动作是否
正确、整体回复质量是否合格。属「结果级」评估。

**怎么评估**：
- 跑全图 `agent.chat()` 得到最终 `reply` + 状态；
- 评估器：
  - `key_facts`：回复是否包含全部 `must_contain` 事实点（如「A1001 / 已发货 / 智能客服机器人 Pro」），规则子串检查；
  - `intent_correct` / `action_correct`：同轨迹评估（意图 + 动作/工具）；
  - `final_answer_correct`：**LLM-as-judge**，比对「理想回复 + 必含事实点 + 评分要点」与实际回复，输出 `is_correct` / `score` / `reasoning`（temperature=0 确定性）；
- 含响应时间统计（min / max / avg / P50）。

**产物**：`answer_eval_cases.json` / `answer_eval_results.json` / `answer_eval_report.md`。

> 全量 1000 条结果：关键事实 29.40%、意图 88.10%、动作/轨迹 56.40%、
> LLM 裁判通过率 37.40%（均分 0.472）；响应时间 最短 0.735s / 最长 50.817s /
> 平均 6.806s / P50 5.644s。主要问题：退款类过度转人工、订单/物流误选工具、轻微幻觉。

---

## 横向对比

| 维度 | 单点 (intent) | 轨迹 (trajectory) | 答案 (answer) |
|---|---|---|---|
| 评估层级 | 组件级（仅路由） | 流程级（节点路径） | 结果级（最终文本） |
| 被测对象 | `IntentRouterService` | 整图 `graph.astream` | 整图 `agent.chat` |
| 调用 LLM | 仅意图路由（可选） | 是（全图，无裁判） | 是（含 LLM 裁判） |
| 核心指标 | 主/子意图准确率 | 节点路径 + 槽位/澄清/工具 | 关键事实 + 意图 + 动作 + 裁判分 |
| 评估方式 | 规则 | 规则（6 项） | 规则 + LLM-as-judge |
| 关键问题 | 认错意图？ | 走错分支/选错工具/漏追问？ | 说错事实/答非所问？ |

## 三者如何关联
- **共享消息分布**：答案评估生成 1000 条，轨迹评估复用同一 seed，结果可横向对比；
- **逐层下钻**：单点发现「意图认错」→ 轨迹里看哪个分支走歪 → 答案里体现为「事实缺失/答非所问」；反之答案暴露的「退款过度转人工」「订单误调物流工具」，在轨迹层被 `action_correct` / `route_correct` 精确捕获为路径级缺陷；
- **互补不重叠**：单点验证路由内核，轨迹验证编排路径，答案验证最终产出——一个查「决策对不对」，一个查「过程对不对」，一个查「结果好不好」。

## 运行方式
```bash
# 单点
python3 eval/intent/run_eval.py            # 规则 + LLM 兜底两种模式

# 轨迹
python3 eval/trajectory/gen_cases.py       # 生成测试集（含轨迹金标）
python3 eval/trajectory/run_eval.py        # 全量 1000 条（规则，无 LLM 裁判）
python3 eval/trajectory/run_eval.py --limit 20

# 答案
python3 eval/answer/gen_cases.py           # 生成测试集
python3 eval/answer/run_eval.py            # 全量 1000 条（含 LLM 裁判）
python3 eval/answer/run_eval.py --no-llm-judge --limit 30
```
