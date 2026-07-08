# 父子意图设计说明

## 1. 什么是父子意图

意图识别的目标是路由到可执行的处理链路，而非给句子贴标签。

父子意图将单层意图拆为两层：

- **父意图（main_intent）**：当前应进入哪条主处理链路？
- **子意图（sub_intent）**：进入该链路后，具体走哪个分支？

示例：`order_service` -> `order_service.query_status`

---

## 2. 为什么用父子意图

### 2.1 单层意图会膨胀

客服场景会持续长出新意图（退款、退货、投诉等）。平铺管理会导致状态机、规则词表、调试信息难以维护。父子意图将这些细分场景收进父类中，先稳定主链路，再细化子流程。

### 2.2 符合工程分层

父意图对应"模块边界"（FAQ / 订单 / 物流 / 售后 / 人工），子意图对应"模块内部动作"，使路由、service 设计、后续扩展更自然。

### 2.3 适合多轮对话

用户常先表达大方向（"我要查订单"），后续靠补槽位、澄清问题收敛到子意图。父子意图天然支持"先粗分，再细分"。

### 2.4 便于调试

双层结构可区分"主链路走错"和"子分支走错"，比单 intent 更容易定位问题。

---

## 3. 当前项目的父子意图映射

| 父意图 | 子意图 | 说明 |
|---|---|---|
| `faq` | `faq.general` | FAQ 检索，不调用业务工具 |
| `order_service` | `order_service.query_status` | 需 `order_id`，缺位时追问 |
| `logistics_service` | `logistics_service.query_status` | 需 `order_id`，缺位时追问 |
| `handoff_service` | `handoff_service.request_human` | 直接进入 handoff，无需复杂槽位 |
| `chitchat` | `chitchat.greeting` | 模板化回复，不进入业务工具链 |
| `unsupported` | `unsupported.unknown` | 兜底，不沿用上一轮业务意图 |

> 未识别时必须显式回到 `unsupported`，不能沿用上一轮状态。

---

## 4. 代码落点

| 层 | 文件 | 职责 |
|---|---|---|
| 数据模型 | `app/models.py` | `IntentResult.main_intent/sub_intent`、`ConversationState.current_main_intent/sub_intent` |
| 路由层 | `app/agent.py` `intent_router()` | 输出主/子意图、槽位、是否需要澄清 |
| 状态跟踪层 | `state_tracker()` | 写入父子意图，决定 stage / 缺槽位 / 是否转人工（父意图为主） |
| 执行层 | — | 按父意图分流：`faq`→FAQ检索，`order_service`→订单工具，`handoff_service`→转人工， etc. |

---

## 5. 分层路由设计

推荐四层顺序决策链：

1. **输入标准化层**：清洗输入、抽取显式标识（如订单号）。对应 `input_normalizer()` / `extract_order_id()`。
2. **高确定性规则层**：用显式规则快速命中高频场景（转人工 > 物流 > 问候 > 订单 > FAQ）。这是当前主路由骨架。
3. **LLM 兜底层**：仅当规则层落到 `fallback` 时触发，处理口语化/省略/弱歧义输入。LLM 是二级兜底，非常规分类器。
4. **DST / 状态决策层**：消费上层结果，写入状态，决定进入执行/追问/转人工/直接回复。

---

## 6. LLM 使用边界

**规则优先，LLM 兜底。** 原因：成本更低、稳定性更好、可解释性更强、便于单点评估。

- 适合 LLM：口语化、省略、轻歧义、边界模糊的输入
- 不适合 LLM（应用规则）：`你好`、`谢谢`、`转人工`、显式订单号/物流查询

---

## 7. 设计原则

1. **父意图不要过细**：父意图对应主链路（如 `order_service`），不是小功能点（如 `query_order_status`）。
2. **子意图必须有差异**：仅在槽位/工具/回复策略/风险等级/澄清方式有明显差异时才拆子意图。
3. **优先保证父意图正确**：主链路走错的成本 >> 子分支不够细。
4. **未识别时回到 `unsupported`**：避免沿用上一轮状态导致误判。

---

## 8. 关键机制

### 8.1 转人工（handoff）

触发条件：用户显式要求、连续多轮无法识别、高风险操作、情绪激烈、工具调用失败。

转人工时应附带：`current_main_intent`、`current_sub_intent`、`slots`、最近消息、当前摘要。当前项目已通过 `handoff_handler()` 生成 `ticket_id` 和摘要。

### 8.2 DST（对话状态跟踪）

状态对象 `ConversationState` 核心字段：`current_main_intent`、`current_sub_intent`、`stage`、`slots`、`missing_slots`、`needs_clarification`、`summary`、`message_history`。

状态更新顺序：清空单轮临时字段 → 写入本轮识别结果 → 合并槽位 → 计算 missing_slots → 设置 stage。

### 8.3 意图切换

- **高优先级打断**（转人工/投诉/安全风险）：立即切换主链路
- **同域切换**（查订单→查物流）：可继承 `order_id`
- **跨域切换**（FAQ→订单）：重置不相关槽位

当前项目通过 `is_intent_shift` 判断切换（新子意图与上一轮不同即切换）。

### 8.4 澄清

触发条件：缺少必填槽位、子意图不稳定、多义输入、高风险需二次确认。

澄清后应推进状态：`missing_slots` 判断 → `needs_clarification=true` → `collecting_info` → 用户补充 → 槽位齐全后进入 `executing`。

---

## 9. 后续扩展建议

1. 新增父意图 `after_sales_service`，子意图：`refund_consult`、`refund_status`、`complaint`
2. 补充 `chitchat.thanks`、`chitchat.goodbye`
3. 扩展 slot schema 支持多槽位抽取
4. 增加状态冻结/存档持久化
5. 完善人机转换上下文，接入真实人工工作台
6. 规则层稳定后，增强 LLM 兜底与相似度召回
