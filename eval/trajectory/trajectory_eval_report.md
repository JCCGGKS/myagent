# 轨迹评估报告

## 总体结果（路径/决策正确性，规则评估，不依赖 LLM 裁判）
- 样本总数：1000
- 节点路径准确率（route）：99.40%
- 意图准确率（intent）：99.90%
- 动作/分支准确率（action）：98.20%
- 槽位抽取准确率（slot_extraction）：100.00%
- 缺失槽位准确率（missing_slot）：100.00%
- 澄清行为准确率（clarification）：99.40%
- **轨迹总准确率（trajectory_overall，六项全过）**：98.20%

## 响应时间（单条样本 agent 跑完整图耗时，含工具调用，不含 LLM 裁判）
- 最短：0.011s
- 最长：13.951s
- 平均：2.882s
- P50：2.725s

## 按类别

| 类别 | 样本数 | 路径 | 意图 | 动作 | 槽位抽取 | 缺失槽位 | 澄清 | 总准确率 | 平均耗时(s) |
|---|---|---|---|---|---|---|---|---|---|
| clarify_no_id | 25 | 80.00% | 100.00% | 80.00% | 100.00% | 100.00% | 80.00% | 80.00% | 1.150 |
| complaint | 55 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 1.431 |
| greeting | 35 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 0.939 |
| handoff | 30 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 0.208 |
| logistics | 140 | 100.00% | 100.00% | 99.29% | 100.00% | 100.00% | 100.00% | 99.29% | 3.474 |
| multiturn_followup | 25 | 100.00% | 100.00% | 56.00% | 100.00% | 100.00% | 100.00% | 56.00% | 2.945 |
| order_query | 236 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 2.698 |
| refund_consult | 187 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 4.381 |
| refund_consult_clarify | 30 | 96.67% | 96.67% | 96.67% | 100.00% | 100.00% | 96.67% | 96.67% | 2.122 |
| refund_request | 212 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 2.892 |
| unsupported | 25 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 1.708 |

## 轨迹未完全达标样本（前 18 条）

- `ans_0076` [multiturn_followup] `A1002 怎么样了`  期望动作 agent_process；实际动作 agent_process 工具 order_query 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0123` [logistics] `A1001 的物流信息`  期望动作 agent_process；实际动作 agent_process 工具 handoff 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0251` [multiturn_followup] `A1001`  期望动作 agent_process；实际动作 agent_process 工具 handoff 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0341` [refund_consult_clarify] `帮我退款`  期望动作 agent_process；实际动作 ask_slot_clarification 工具 None 回复节点 clarification_node
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'clarification_node', 'context_compressor']
    - 未过维度：路径/意图/动作/澄清
- `ans_0406` [multiturn_followup] `A1001 怎么样了`  期望动作 agent_process；实际动作 agent_process 工具 logistics 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0428` [multiturn_followup] `帮我催一下 A1001`  期望动作 agent_process；实际动作 agent_process 工具 handoff 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0467` [clarify_no_id] `帮我看看我买的东西`  期望动作 ask_slot_clarification；实际动作 agent_process 工具 order_query 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'clarification_node', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：路径/动作/澄清
- `ans_0493` [multiturn_followup] `再等等 A1001`  期望动作 agent_process；实际动作 agent_process 工具 logistics 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0560` [multiturn_followup] `再等等 A1001`  期望动作 agent_process；实际动作 agent_process 工具 logistics 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0624` [multiturn_followup] `帮我催一下 A1001`  期望动作 agent_process；实际动作 agent_process 工具 logistics 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0636` [multiturn_followup] `帮我催一下 A1001`  期望动作 agent_process；实际动作 agent_process 工具 logistics 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0638` [clarify_no_id] `我想看看我买的东西`  期望动作 ask_slot_clarification；实际动作 agent_process 工具 order_query 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'clarification_node', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：路径/动作/澄清
- `ans_0665` [clarify_no_id] `请问看看我买的东西`  期望动作 ask_slot_clarification；实际动作 agent_process 工具 order_query 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'clarification_node', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：路径/动作/澄清
- `ans_0719` [clarify_no_id] `看看我买的东西`  期望动作 ask_slot_clarification；实际动作 agent_process 工具 order_query 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'clarification_node', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：路径/动作/澄清
- `ans_0830` [clarify_no_id] `麻烦看看我买的东西`  期望动作 ask_slot_clarification；实际动作 agent_process 工具 order_query 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'clarification_node', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：路径/动作/澄清
- `ans_0859` [multiturn_followup] `A1001 怎么样了`  期望动作 agent_process；实际动作 agent_process 工具 handoff 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0907` [multiturn_followup] `A1001 怎么样了`  期望动作 agent_process；实际动作 agent_process 工具 order_query 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
- `ans_0944` [multiturn_followup] `帮我催一下 A1002`  期望动作 agent_process；实际动作 agent_process 工具 logistics 回复节点 response_generator
    - 期望路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 实际路径 ['input_normalizer', 'intent_router', 'state_tracker', 'policy_layer', 'agent_node', 'response_generator', 'context_compressor']
    - 未过维度：动作
