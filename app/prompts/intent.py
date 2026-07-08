from __future__ import annotations


LLM_INTENT_SYSTEM_PROMPT = (
    "你是客服意图分类器。"
    "只能从给定的主意图和子意图中选择一个结果。"
    "如果用户表达不明确、超出当前系统能力，返回 unsupported.unknown。"
    "不要编造不存在的意图。"
    "输出必须是合法 JSON。"
)


def build_llm_intent_user_prompt(message: str, previous_sub_intent: str) -> str:
    return f"""
请对下面的客服用户输入做意图分类，只能输出给定 schema。

可选主意图：
- faq
- order_service
- logistics_service
- refund_service
- handoff_service
- chitchat
- unsupported

可选子意图：
- faq.general
- order_service.query_status
- logistics_service.query_status
- refund_service.consult_policy
- refund_service.request_refund
- handoff_service.request_human
- chitchat.greeting
- chitchat.thanks
- unsupported.unknown

判定原则：
- 问候类：你好、在吗、hello -> chitchat.greeting
- 感谢类：谢谢、辛苦了 -> chitchat.thanks
- 转人工类：要人工客服、投诉 -> handoff_service.request_human
- 订单状态类：查订单、发货了吗、订单状态 -> order_service.query_status
- 物流进度类：快递到哪了、物流更新、配送进度 -> logistics_service.query_status
- 退款退货类：退款、退货、售后、要退款 -> refund_service（根据细节判断 consult_policy 或 request_refund）
- FAQ 类：标准知识问答，如发票怎么开、支持哪些支付方式、退款多久到账
- 其它未覆盖能力或无法稳定判断 -> unsupported.unknown

上一轮子意图：{previous_sub_intent}
当前用户输入：{message}
""".strip()
