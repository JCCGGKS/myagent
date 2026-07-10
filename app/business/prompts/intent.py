from __future__ import annotations


LLM_INTENT_SYSTEM_PROMPT = (
    "你是客服意图分类器。"
    "只能从给定的主意图和子意图中选择一个结果。"
    "如果用户表达不明确、超出当前系统能力，返回 unrecognize.unknown。"
    "不要编造不存在的意图。"
    "输出必须是合法 JSON。"
)


def build_llm_intent_user_prompt(message: str, previous_sub_intent: str) -> str:
    return f"""
请对下面的客服用户输入做意图分类，只能输出给定 schema。

可选主意图：
- order_query
- logistics
- after_sale_refund
- complaint
- handoff_service
- unrecognize
- unsupported_biz

可选子意图：
- order_query.query_status
- order_query.modify_address
- order_query.apply_invoice
- logistics.lost_package
- logistics.delayed
- logistics.not_received
- after_sale_refund.damage_refund
- after_sale_refund.no_reason_return
- after_sale_refund.wrong_goods
- complaint.compensate
- complaint.service_complaint
- handoff_service.request_human
- unrecognize.unknown
- unsupported_biz.out_of_scope

判定原则：
- 简单问候（你好、在吗、hello）不属于业务咨询，返回 unrecognize.unknown
- 转人工类：要人工客服、投诉 -> handoff_service.request_human
- 订单类：查订单、发货了吗、订单状态 -> order_query.query_status
- 物流类：快递到哪了、物流更新、配送进度、丢件 -> logistics.not_received
- 退款售后类：退款、退货、售后、要退款 -> after_sale_refund（根据细节判断 consult_policy 或 request_refund）
- 投诉类：投诉、差评、赔付、太差了、情绪激动 -> complaint
- 超出业务范围：招聘、加盟等 -> unsupported_biz
- 其它未覆盖能力或无法稳定判断 -> unrecognize.unknown
- 多意图时以用户最终目的为准。

上一轮子意图：{previous_sub_intent}
当前用户输入：{message}
""".strip()
