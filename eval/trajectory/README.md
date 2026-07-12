# 轨迹评估（Trajectory Evaluation）

与 [`../answer`](../answer) 互补：**answer 评估「说得好不好」（最终文本）**，
**trajectory 评估「走得对不对」（决策路径）**。

仿照 LangSmith「Evaluate a complex agent」的方法论，但把评估对象从最终回复
换成 agent 在 LangGraph 中走过的**完整节点序列与决策链**：

```
dataset(inputs / outputs=reference+轨迹金标)  ──►  target: graph.astream 捕获轨迹  ──►  evaluators(规则)
```

## 数据集（`trajectory_eval_cases.json`）

由 [`gen_cases.py`](gen_cases.py) 生成，**复用 answer 评估的同一 1000 条样本**
（相同 seed、相同消息分布），在其上追加轨迹金标字段：

| 字段 | 含义 |
|---|---|
| `expected_node_path` | 期望执行的节点序列（BASE + 动作分支 + `context_compressor`） |
| `expected_reply_source_node` | 最终回复产出节点（`clarification_node` / `response_generator`） |
| `expected_order_id` | 消息中应由 `state.slots` 抽出的订单号（无则 `null`） |
| `expected_missing_slots` | 期望缺失槽位（意图需要订单号且消息无单号 → `["order_id"]`） |
| `expected_needs_clarification` | 是否应进入澄清 |

节点路径映射（与 `app/business/agent/graph.py` 一致）：

| 期望动作 | 期望节点路径 |
|---|---|
| `agent_process` | input_normalizer → intent_router → state_tracker → policy_layer → **agent_node** → response_generator → context_compressor |
| `handoff_human` | … → **handoff_node** → response_generator → context_compressor |
| `ask_intent_clarification` / `ask_slot_clarification` | … → **clarification_node** → context_compressor |
| `answer_directly` | … → response_generator → context_compressor |

## 运行器（`run_eval.py`）

`target` 用 `graph.astream` 逐步捕获：

- `node_order`：实际节点执行顺序；
- `intent`：intent_router 产出的主/子意图；
- `slots` / `missing_slots`：state_tracker 之后状态；
- `action` + `tool_kind`：policy_layer 决策 + agent_node 调用的工具 kind；
- `reply_source_node`：最终回复由哪个节点产出。

### Evaluators（全部规则判定，确定性、不依赖 LLM 裁判）

| 评估器 | 判定标准 |
|---|---|
| `route_correct` | 实际节点序列 == 期望节点序列（含分支与 context_compressor） |
| `intent_correct` | 预测主/子意图 == 期望 |
| `action_correct` | 预测动作 == 期望；`agent_process` 时再校验工具 kind |
| `slot_extraction_correct` | 消息含订单号时，`state.slots` 正确抽出该 order_id |
| `missing_slot_correct` | 预测缺失槽位 == 期望缺失槽位 |
| `clarification_correct` | `needs_clarification` 与期望一致；澄清类还需 reply 实际追问订单号 |
| `trajectory_overall` | 以上六项全过 = 端到端走对路径 |

### 指标聚合

总准确率 + 按类别拆解（路径/意图/动作/槽位抽取/缺失槽位/澄清/总准确率 + 平均耗时）
+ **响应时间统计**（min / max / avg / P50，单条样本跑完整图耗时，含工具调用）。

## 用法

```bash
python3 eval/trajectory/gen_cases.py          # 生成（覆盖）测试集
python3 eval/trajectory/run_eval.py           # 全量 1000 条
python3 eval/trajectory/run_eval.py --limit 20        # 小样本验证
python3 eval/trajectory/run_eval.py --max-concurrency 8
```

## 与 answer 评估的关系

- answer 评估已发现：退款类过度转人工、订单/物流工具选错、轻微幻觉。
- trajectory 评估从「路径」维度独立验证上述问题：例如 `order_query` 调 `logistics`
  工具会在 `action_correct` 维度暴露为「动作对但工具 kind 错」；这与 answer 评估的
  `action` 维度一致，但 trajectory 额外给出**节点路径**与**槽位/澄清行为**的细粒度信号。
- 两者使用同一消息分布，结果可直接横向对比。
