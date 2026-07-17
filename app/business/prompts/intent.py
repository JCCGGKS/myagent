from __future__ import annotations

from app.schema import ConversationState
from app.schema.intent import MAIN_INTENT_CODES, SUB_INTENT_CODES


LLM_INTENT_SYSTEM_PROMPT = (
    "你是客服意图分类器。"
    "只能从给定的主意图和子意图中选择一个。"
    "能从文本抽取的实体（如 order_id 订单号，通常以字母+数字出现，如 A1001、SF123）请填入 slots.order_id。"
    "同时判断用户情绪，输出 emotion 字段，取值只能是 neutral / positive / negative"
    "（无明显情绪→neutral；投诉/差评/发火/着急/担心→negative；感谢/满意→positive）。"
    "如果用户表达不明确、超出当前系统能力，返回 unrecognize.unknown。"
    "不要编造不存在的意图或实体。"
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


def build_llm_intent_user_prompt(
    message: str,
    previous_sub_intent: str = "",
    state: ConversationState | None = None,
) -> str:
    # 优先从状态对象借用上下文（上下文隔离：只取上一轮子意图，
    # 不直接透传整份状态，避免把无关字段喂给 LLM）。
    if state is not None:
        previous_sub_intent = state.current_sub_intent
    main_lines, sub_lines = _build_intent_lists()
    return     f"""
请对下面的客服用户输入做意图分类，只能输出给定 schema。
除 main_intent / sub_intent / slots / confidence / needs_clarification 外，
还需输出 emotion（neutral / positive / negative）。

可选主意图：
{main_lines}

可选子意图：
{sub_lines}

判定原则：
- 简单问候（你好、在吗、有人吗、hello、随便聊聊）不属于业务咨询，返回 unrecognize.unknown
- 转人工类：要人工客服、投诉 -> handoff_service.request_human
- 订单类：查订单、发货了吗、订单状态 -> order_query（按需选 query_status / modify_address / apply_invoice）
  · 改地址 / 修改地址 -> order_query.modify_address
  · 开发票 -> order_query.apply_invoice
- 物流类：快递到哪了、物流更新、配送进度、丢件 -> logistics（按需选 not_received / lost_package / delayed）
  · 仅询问配送/到货进度、未明确说「丢件/丢失/延迟/太慢」时，默认 logistics.not_received
  · 明确说丢件/包裹丢了 -> logistics.lost_package
  · 明确说延迟/太慢/好慢 -> logistics.delayed
- 退款售后类：退款、退货、售后、要退款 -> after_sale_refund，按细节判断：
  · 咨询退款政策、仅说「质量/坏了/有问题」但未明确要退 -> after_sale_refund.consult_policy
  · 明确要申请退款（我要退款/申请退/想退/后悔了/退掉） -> after_sale_refund.request_refund
  · 商品损坏退款 -> after_sale_refund.damage_refund
  · 无理由/七天无理由退货退款 -> after_sale_refund.no_reason_return
  · 收到错货/发错货 -> after_sale_refund.wrong_goods
- 投诉类：投诉、差评、太差了、情绪激动 -> complaint（compensate / service_complaint）
  · 明确说赔偿/赔付 -> complaint.compensate
- 超出业务范围：招聘、加盟等 -> unsupported_biz.out_of_scope
- 其它未覆盖能力或无法稳定判断 -> unrecognize.unknown

示例：
- 「改一下收货地址」 -> order_query.modify_address
- 「麻烦开个发票」 -> order_query.apply_invoice
- 「我的快递丢件了」 -> logistics.lost_package
- 「物流怎么这么慢」 -> logistics.delayed
- 「我的货到哪了」 -> logistics.not_received
- 「买的东西想退」 -> after_sale_refund.request_refund
- 「收到的东西坏了要退款」 -> after_sale_refund.damage_refund
- 「七天无理由退货」 -> after_sale_refund.no_reason_return
- 「发错货了」 -> after_sale_refund.wrong_goods
- 「要求赔偿」 -> complaint.compensate
- 「有人吗」 -> unrecognize.unknown

上一轮子意图：{previous_sub_intent}
当前用户输入：{message}
""".strip()
