# 轨迹评估报告

## 总体结果（路径/决策正确性，规则评估，不依赖 LLM 裁判）
- 样本总数：15
- 节点路径准确率（route）：100.00%
- 意图准确率（intent）：93.33%
- 动作/分支准确率（action）：66.67%
- 槽位抽取准确率（slot_extraction）：100.00%
- 缺失槽位准确率（missing_slot）：100.00%
- 澄清行为准确率（clarification）：100.00%
- **轨迹总准确率（trajectory_overall，六项全过）**：60.00%

## 响应时间（单条样本 agent 跑完整图耗时，含工具调用，不含 LLM 裁判）
- 最短：0.829s
- 最长：18.416s
- 平均：6.364s
- P50：5.404s

## 按类别

| 类别 | 样本数 | 路径 | 意图 | 动作 | 槽位抽取 | 缺失槽位 | 澄清 | 总准确率 | 平均耗时(s) |
|---|---|---|---|---|---|---|---|---|---|
| clarify_no_id | 1 | 6.67% | 6.67% | 6.67% | 6.67% | 6.67% | 6.67% | 6.67% | 0.829 |
| logistics | 1 | 6.67% | 6.67% | 0.00% | 6.67% | 6.67% | 6.67% | 0.00% | 7.717 |
| order_query | 6 | 40.00% | 40.00% | 26.67% | 40.00% | 40.00% | 40.00% | 26.67% | 4.611 |
| refund_consult | 3 | 20.00% | 13.33% | 20.00% | 20.00% | 20.00% | 20.00% | 13.33% | 6.929 |
| refund_consult_clarify | 1 | 6.67% | 6.67% | 6.67% | 6.67% | 6.67% | 6.67% | 6.67% | 18.416 |
| refund_request | 3 | 20.00% | 20.00% | 6.67% | 20.00% | 20.00% | 20.00% | 6.67% | 6.682 |

## 轨迹未完全达标样本（前 6 条）

- `ans_0054` [refund_request] `A1001 的退掉这单`  期望动作 agent_process；实际动作 agent_process 工具 knowledge 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0005` [order_query] `请问单号A1002，帮我查下订单`  期望动作 agent_process；实际动作 agent_process 工具 knowledge 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0009` [order_query] `订单详情，单号A1001`  期望动作 agent_process；实际动作 agent_process 工具 logistics 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0421` [refund_consult] `七天无理由怎么退，单号A1002`  期望动作 agent_process；实际动作 agent_process 工具 knowledge 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：意图
- `ans_0014` [logistics] `请问单号A1001，货到没到`  期望动作 agent_process；实际动作 agent_process 工具 order_query 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0015` [refund_request] `麻烦A1002 的退掉这单`  期望动作 agent_process；实际动作 agent_process 工具 handoff 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
