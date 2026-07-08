# 意图识别单点评估报告（规则 + LLM 兜底）

## 评估方式

评估 `IntentRouterService` 的完整路由链路，包括：

- 规则匹配（关键词、FAQ 知识库、slot 跟随）
- LLM 兜底（规则未匹配时调用 LLM 做意图分类）

## 总体结果

- 样本总数：42
- 命中样本：25
- 准确率：59.52%
- 路由来源分布：
  - `rule`: 35
  - `fallback`: 7

## 按主意图统计

- `chitchat`: 6 / 7 = 85.71%
- `faq`: 5 / 8 = 62.50%
- `handoff_service`: 2 / 2 = 100.00%
- `logistics_service`: 4 / 5 = 80.00%
- `order_service`: 4 / 5 = 80.00%
- `unsupported`: 4 / 15 = 26.67%

## 未覆盖/误判样本

- `faq_refund_exact`: `退款多久到账` -> expected `faq / faq.general`, actual `refund_service / refund_service.consult_policy` (source=rule)
- `faq_refund_variant`: `退款几天到账` -> expected `faq / faq.general`, actual `refund_service / refund_service.consult_policy` (source=rule)
- `faq_refund_arrival_variant`: `退款什么时候到账` -> expected `faq / faq.general`, actual `refund_service / refund_service.consult_policy` (source=rule)
- `faq_refund_policy`: `退款规则是什么` -> expected `unsupported / unsupported.unknown`, actual `refund_service / refund_service.consult_policy` (source=rule)
- `faq_refund_policy_variant`: `可以退款吗` -> expected `unsupported / unsupported.unknown`, actual `refund_service / refund_service.consult_policy` (source=rule)
- `refund_request_direct`: `我要退款` -> expected `unsupported / unsupported.unknown`, actual `refund_service / refund_service.request_refund` (source=rule)
- `refund_request_action`: `帮我申请退款` -> expected `unsupported / unsupported.unknown`, actual `refund_service / refund_service.request_refund` (source=rule)
- `refund_request_progress_like`: `退款怎么处理` -> expected `unsupported / unsupported.unknown`, actual `refund_service / refund_service.consult_policy` (source=rule)
- `refund_request_short`: `退款` -> expected `unsupported / unsupported.unknown`, actual `refund_service / refund_service.consult_policy` (source=rule)
- `order_status_delivery_variant`: `我的订单发没发` -> expected `unsupported / unsupported.unknown`, actual `order_service / order_service.query_status` (source=rule)
- `order_followup_id_only`: `A1001` -> expected `order_service / order_service.query_status`, actual `unsupported / unsupported.unknown` (source=fallback)
- `logistics_variant_package`: `包裹到哪了` -> expected `unsupported / unsupported.unknown`, actual `logistics_service / logistics_service.query_status` (source=rule)
- `logistics_followup_id_only`: `A1002` -> expected `logistics_service / logistics_service.query_status`, actual `unsupported / unsupported.unknown` (source=fallback)
- `thanks_variant`: `辛苦了` -> expected `chitchat / chitchat.thanks`, actual `unsupported / unsupported.unknown` (source=fallback)
- `unsupported_complaint`: `我要投诉` -> expected `unsupported / unsupported.unknown`, actual `handoff_service / handoff_service.request_human` (source=rule)
- `unsupported_shipping_variant`: `什么时候能收到货` -> expected `unsupported / unsupported.unknown`, actual `faq / faq.general` (source=rule)
- `unsupported_invoice_change`: `发票可以修改吗` -> expected `unsupported / unsupported.unknown`, actual `faq / faq.general` (source=rule)

## 结论

规则层优先处理显式表达，LLM 兜底覆盖规则未匹配的口语化、同义表达。

