# 意图识别第一轮评估分析与改进方案

## 评估概况

- 评估时间：2025-07
- 样本规模：1000 条
- 评估脚本：`eval/run_eval.py`
- 评估方式：直接调用 `IntentRouterService.route()`，与生产代码路径一致

| 模式 | 准确率 | 命中数 |
|---|---|---|
| 规则-only | 55.00% | 550/1000 |
| 规则+LLM | 75.70% | 757/1000 |
| LLM 提升 | +20.70% | +207 |

路由来源分布（规则+LLM）：
- 规则命中：387
- 未识别（走兜底）：103
- LLM 兜底：510

> **注意**：`llm_fallback_hits` 计数异常，显示为 0，实际应为 510。见问题 5。

---

## 问题 1：规则关键词覆盖不足（最主要问题）

### 现象

大量口语化表达没有命中任何规则关键词，直接掉进「未识别（走兜底）」或走「LLM 兜底」，而 LLM 兜底对这些短句的判断也不稳定。

### 典型失败 case

| message | expected | actual | route_source |
|---|---|---|---|
| `收到坏的了` | `after_sale_refund.damage_refund` | `unrecognize.unknown` | 未识别（走兜底） |
| `东西有问题我要退` | `after_sale_refund.damage_refund` | `unrecognize.unknown` | 未识别（走兜底） |
| `发错货了` | `after_sale_refund.wrong_goods` | `unrecognize.unknown` | 未识别（走兜底） |
| `不想要了能退吗` | `after_sale_refund.no_reason_return` | `unrecognize.unknown` | 未识别（走兜底） |
| `我不想买了能退吗` | `after_sale_refund.no_reason_return` | `unrecognize.unknown` | 未识别（走兜底） |
| `机器人听不懂` | `handoff_service.request_human` | `unrecognize.unknown` | 未识别（走兜底）/ LLM 兜底 |
| `叫你们负责人来` | `handoff_service.request_human` | `unrecognize.unknown` | 未识别（走兜底） |
| `不想跟机器人说话` | `handoff_service.request_human` | `unrecognize.unknown` | 未识别（走兜底） |
| `A1346`（纯订单号，无上下文） | 各意图 | `unrecognize.unknown` | LLM 兜底 |

### 根因

`config/intent_rules.yml` 的关键词集合过于狭窄，没有覆盖口语化表达：

- `handoff_keywords` 只有：`转人工`、`人工客服`、`找人工` → 缺少：`机器人听不懂`、`叫你们负责人`、`不想跟机器人`
- `after_sale_refund_keywords` 只有：`退货`、`售后`、`退换`、`换货`、`退款` → 缺少：`坏了`、`有问题`、`发错`、`质量差`
- `complaint_keywords` 有 `赔偿` 但规则优先级导致误判（见问题 2）

### 解决方案

**修改 `config/intent_rules.yml`，补充关键词：**

```yaml
handoff_keywords:      # 现有 3 个 → 建议增加到 8+ 个
  - 转人工、人工客服、找人工
  + 机器人听不懂、叫你们负责人来、不想跟机器人、人工、要人工

after_sale_refund_keywords:  # 现有 5 个 → 建议增加到 10+ 个
  - 退货、售后、退换、换货、退款
  + 坏了、有问题、发错、质量差、不满意、不想要了

complaint_keywords:
  + 机器人听不懂、太差了、无法接受
```

**预期效果**：规则-only 准确率预计从 55% 提升到 65-70%。

---

## 问题 2：规则优先级导致 after_sale_refund 被误判为 complaint

### 现象

以下 case 的 actual 是 `complaint.service_complaint`（rule 来源），但 expected 是 `after_sale_refund` 相关子意图。

| message | expected | actual |
|---|---|---|
| `给我赔偿` | `complaint.compensate` | `complaint.service_complaint` |
| `质量太差了要退款` | `after_sale_refund.damage_refund` | `complaint.service_complaint` |

### 根因

`app/services/routing.py:78`：

```python
elif has_complaint_keyword or emotion.primary == "negative":
    intent = IntentResult(main_intent="complaint", ...)
```

「质量太差了」命中 `complaint_keywords`（「太差了」），直接走 complaint 分支，不会再判断 after_sale_refund。

### 解决方案

**方案 A**（推荐）：调整规则顺序，售后关键词优先于投诉关键词。

将 after_sale_refund 判断（目前在第 5 位）提前到 complaint 之前，并在 complaint 分支里加例外：如果同时命中 after_sale_refund 关键词，走售后。

**方案 B**：把 `complaint_keywords` 里的「太差了」移到单独的 emotion 检测，不直接走 complaint 路由。

---

## 问题 3：`unrecognize` vs `unsupported_biz` 意图不一致

### 现象

LLM fallback 把「今天天气怎么样」「怎么加盟」「你们招人吗」分成 `unsupported_biz.out_of_scope`，但评估样本的 `expected_main_intent` 是 `unrecognize`。

| message | expected | actual (LLM) |
|---|---|---|
| `今天天气怎么样` | `unrecognize.unknown` | `unsupported_biz.out_of_scope` |
| `怎么加盟` | `unrecognize.unknown` | `unsupported_biz.out_of_scope` |
| `你们招人吗` | `unrecognize.unknown` | `unsupported_biz.out_of_scope` |

### 根因

系统已支持 `unsupported_biz` 意图（LLM fallback 会返回），但评估样本的 expected 值还停留在 `unrecognize`。

### 解决方案

**统一意图定义**：确认 `config/intent_schemas.yml` 是否有 `unsupported_biz`，如果有，将评估样本里「明显超出业务范围的请求」的 expected 改为 `unsupported_biz.out_of_scope`；「无法理解的表达」保留 `unrecognize.unknown`。

---

## 问题 4：纯订单号（如 `A1346`）无法判断意图

### 现象

100 条 followup 样本里有很多纯订单号（如 `A1346`、`A1233`），但评估时 `state.current_sub_intent` 初始为空，导致 `routing.py:166` 的 `slot_followup` 逻辑不触发。

### 根因

评估脚本构造 `ConversationState` 时没有设置 `current_sub_intent`，多轮上下文丢失。

### 解决方案

**修改 `eval/run_eval.py`**：对含 `previous_sub_intent` 字段的 case，正确初始化 state：

```python
state = ConversationState(session_id="eval", user_id="eval", channel="eval")
if case.get("previous_sub_intent"):
    state.current_main_intent = case["previous_sub_intent"].split(".")[0]
    state.current_sub_intent = case["previous_sub_intent"]
```

---

## 问题 5：`llm_fallback_hits` 计数异常

### 现象

对比报告显示 `LLM 兜底命中：0 次`，但路由分布里「LLM 兜底：510」。

### 根因

`run_eval.py:66` 的计数逻辑：

```python
if actual.route_source == "llm_fallback":
    llm_hits += 1
```

但 `IntentRouterService` 在 `routing.py:210-219` 有「规则置信度低时用 LLM 覆盖」逻辑，覆盖后 `route_source` 可能还是 `"rule"` 而非 `"llm_fallback"`，导致漏计。

### 解决方案

**方案 A**：在 `IntentRouterService` 里，LLM 覆盖规则结果时，把 `route_source` 改为 `llm_fallback`。

**方案 B**（更简单）：在 `run_eval.py` 里，除了 `route_source == "llm_fallback"`，也计数「规则命中的意图与 LLM 返回意图不同」的情况。

---

## 改进优先级

| 优先级 | 问题 | 预计准确率提升 | 工作量 |
|---|---|---|---|
| P0 | 问题 1：补充规则关键词 | +10-15% | 小 |
| P0 | 问题 4：修复 eval 脚本多轮上下文 | 数据质量 | 小 |
| P1 | 问题 5：修复 `llm_fallback_hits` 计数 | 度量准确性 | 小 |
| P1 | 问题 2：调整规则优先级 | +2-5% | 中 |
| P2 | 问题 3：统一 `unrecognize`/`unsupported_biz` | 数据质量 | 中 |

---

## 下一步

1. 补充 `config/intent_rules.yml` 关键词（问题 1）
2. 修复 `eval/run_eval.py` 多轮上下文初始化（问题 4）
3. 修复 `llm_fallback_hits` 计数（问题 5）
4. 重新跑全量评估，验证改进效果
5. 根据新结果调整规则优先级（问题 2）
