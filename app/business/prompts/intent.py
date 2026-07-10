from __future__ import annotations

from app.schema.intent import MAIN_INTENT_CODES, SUB_INTENT_CODES


LLM_INTENT_SYSTEM_PROMPT = (
    "你是客服意图分类器。"
    "只能从给定的主意图和子意图中选择一个结果。"
    "如果用户表达不明确、超出当前系统能力，返回 unrecognize.unknown。"
    "不要编造不存在的意图。"
    "输出必须是合法 JSON。"
)


def _group_sub_intents() -> dict[str, list[str]]:
    """按主意图分组子意图，供提示词动态生成。"""
    groups: dict[str, list[str]] = {main: [] for main in MAIN_INTENT_CODES}
    for sub in SUB_INTENT_CODES:
        main, _, tail = sub.partition(".")
        groups.setdefault(main, []).append(sub)
    return groups


def _build_intent_lists() -> tuple[str, str]:
    """基于权威枚举动态生成「可选主意图 / 子意图」列表文本。"""
    main_lines = "\n".join(f"- {m}" for m in sorted(MAIN_INTENT_CODES))
    groups = _group_sub_intents()
    sub_lines = "\n".join(
        f"- {s}" for m in sorted(groups) for s in groups[m]
    )
    return main_lines, sub_lines


def build_llm_intent_user_prompt(message: str, previous_sub_intent: str) -> str:
    main_lines, sub_lines = _build_intent_lists()
    return f"""
请对下面的客服用户输入做意图分类，只能输出给定 schema。

可选主意图：
{main_lines}

可选子意图：
{sub_lines}

判定原则：
- 简单问候（你好、在吗、hello）不属于业务咨询，返回 unrecognize.unknown
- 转人工类：要人工客服、投诉 -> handoff_service.request_human
- 订单类：查订单、发货了吗、订单状态 -> order_query（按需选 query_status / modify_address / apply_invoice）
- 物流类：快递到哪了、物流更新、配送进度、丢件 -> logistics（按需选 not_received / lost_package / delayed）
- 退款售后类：退款、退货、售后、要退款 -> after_sale_refund，按细节判断：
  · 咨询退款政策 -> after_sale_refund.consult_policy
  · 明确要申请退款 -> after_sale_refund.request_refund
  · 商品损坏退款 -> after_sale_refund.damage_refund
  · 无理由退货退款 -> after_sale_refund.no_reason_return
  · 收到错货 -> after_sale_refund.wrong_goods
- 投诉类：投诉、差评、赔付、太差了、情绪激动 -> complaint（compensate / service_complaint）
- 超出业务范围：招聘、加盟等 -> unsupported_biz.out_of_scope
- 其它未覆盖能力或无法稳定判断 -> unrecognize.unknown
- 多意图时以用户最终目的为准。

上一轮子意图：{previous_sub_intent}
当前用户输入：{message}
""".strip()
