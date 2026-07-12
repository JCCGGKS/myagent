"""最终回复评估测试集生成器（仿 LangSmith 复杂 Agent 评估数据结构）。

生成 ``answer_eval_cases.json``，作为「最终回复评估」的数据集。每条样本对齐
LangSmith 的 example 结构：

    {
      "id": "ans_0001",
      "category": "order_query",
      "inputs":  {"message": "...", "session_id": "ans-sess-0001"},
      "outputs": {                                   # 即 reference / ground truth
        "expected_main_intent": "order_query",
        "expected_sub_intent": "order_query.query_status",
        "expected_action": "agent_process",          # 决策动作（见 HandoffClarificationPolicy）
        "expected_tool": "order_query",              # agent_process 时调用的工具 kind
        "reference_reply": "订单 A1001 当前状态为已发货……",  # 理想回复（供 LLM 裁判比对）
        "must_contain": ["A1001", "已发货"],          # 确定性事实核查点（规则评估用）
        "rubric": "应返回订单状态、商品与金额，语气友好专业。"
      }
    }

设计要点：
- 覆盖 agent 五条最小闭环能力 + 问候闲聊 + 超出范围 + 投诉 + 澄清 + 多轮跟进；
- 订单/物流/退款等需要事实的类别，仅使用 ``app/data`` 中真实存在的订单数据
  （A1001 / A1002）构造可验证的 ``must_contain``，避免凭空断言；
- 每个样本分配**唯一** ``session_id``，避免评估时 checkpointer 跨样本串状态；
- 去重（同 message + 同上下文视为重复），目标 1000 条，按类别保底抽样。

用法：
  python3 eval/answer/gen_cases.py            # 重新生成（覆盖）测试集
  python3 eval/answer/gen_cases.py --count N  # 目标样本数（默认 1000）
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# 真实存在的订单数据（来自 app/data/orders.json / logistics.json）
KNOWN_ORDERS = {
    "A1001": {"status": "已发货", "product_name": "智能客服机器人 Pro", "amount": 1999.0,
              "logistics": {"tracking_status": "运输中", "latest": "2026-07-03 10:00 派送中"}},
    "A1002": {"status": "待付款", "product_name": "知识库增强包", "amount": 399.0,
              "logistics": None},
}

# 前缀（口语化，不影响意图）
PREFIXES = ["", "麻烦", "请问", "我想", "帮我"]

# 仅使用不会拼接出其它意图关键词的安全前缀组合
ORDER_IDS = ["A1001", "A1002"]
LOGISTICS_IDS = ["A1001"]  # 仅 A1001 有物流数据


def _norm(text: str) -> str:
    return " ".join(text.split()).strip()


def _fmt_amount(amount: float) -> str:
    # 1999.0 -> "1999"，399.0 -> "399"
    return f"{amount:g}"


# =========================================================================
# 类别定义：(category, main, sub, action, tool, bases, 是否带订单号, clarification?)
# =========================================================================

# 1) 订单查询（agent_process + order_query 工具）
ORDER_QUERY = (
    "order_query", "order_query", "order_query.query_status",
    "agent_process", "order_query", False,
    ["查订单", "订单状态", "我的订单", "帮我查下订单", "看看我的单", "发货了吗", "订单详情"],
)

# 2) 物流查询（agent_process + logistics 工具，仅 A1001）
LOGISTICS = (
    "logistics", "logistics", "logistics.not_received",
    "agent_process", "logistics", False,
    ["物流", "快递到哪了", "配送进度", "什么时候送到", "物流信息", "包裹到哪了", "货到没到"],
)

# 3) 退款申请（agent_process + aftersale_refund 工具）
REFUND_REQUEST = (
    "refund_request", "after_sale_refund", "after_sale_refund.request_refund",
    "agent_process", "aftersale_refund", False,
    ["我要退款", "申请退款", "帮我退款", "退掉这单", "退货退款", "这单不想要了退了吧"],
)

# 4) 退款咨询（带订单号 -> agent_process；咨询为信息性，不强校验工具调用）
REFUND_CONSULT_WITH_ID = (
    "refund_consult", "after_sale_refund", "after_sale_refund.consult_policy",
    "agent_process", None, False,
    ["退款规则", "怎么退款", "退款政策", "退换货政策", "七天无理由怎么退"],
)

# 5) 退款咨询（无订单号）：仅 action 关键词（我要退款/申请退款…）才追问订单号；
#    普通「退款/退货/售后」表述按规则设计直接走 agent_process（LLM 解释政策）。
#    故期望动作 = agent_process，不强制追问。
REFUND_CONSULT_NO_ID = (
    "refund_consult_clarify", "after_sale_refund", "after_sale_refund.consult_policy",
    "agent_process", None, True,
    ["退款", "退货", "售后", "退换", "换货", "质量问题怎么退"],
)

# 6) 转人工（handoff_human）
HANDOFF = (
    "handoff", "handoff_service", "handoff_service.request_human",
    "handoff_human", "handoff", True,
    ["转人工", "人工客服", "找人工", "真人客服", "我要人工", "别跟机器人说了"],
)

# 7) 问候闲聊（answer_directly）
GREETING = (
    "greeting", "unrecognize", "unrecognize.unknown",
    "answer_directly", None, True,
    ["你好", "在吗", "嗨", "有人吗", "今天天气真好", "随便聊聊", "在不在"],
)

# 8) 超出业务范围（answer_directly）
UNSUPPORTED = (
    "unsupported", "unsupported_biz", "unsupported_biz.out_of_scope",
    "answer_directly", None, True,
    ["你们招人吗", "怎么加盟", "你们有代理吗", "我想应聘", "怎么成为供应商"],
)

# 9) 投诉（agent_process，同情安抚）
COMPLAINT = (
    "complaint", "complaint", "complaint.service_complaint",
    "agent_process", None, True,
    ["投诉", "太差了", "差评", "气死我了", "没用", "越想越气", "你们这态度我真服了"],
)

# 10) 澄清：订单类意图但缺订单号（ask_slot_clarification）
CLARIFY_NO_ID = (
    "clarify_no_id", "order_query", "order_query.query_status",
    "ask_slot_clarification", None, True,
    ["查订单", "我的订单", "订单状态", "帮我查单", "看看我买的东西"],
)


def _order_id_variants(base: str, oid: str) -> list[str]:
    """为带订单号的类别生成多种口语化变体。"""
    return [
        f"{base}，单号{oid}",
        f"单号{oid}，{base}",
        f"{base} {oid}",
        f"{oid} 的{base}",
    ]


def _build_category(spec: tuple, target: int | None = None) -> list[dict]:
    """展开一个类别为多条样本。

    spec = (category, main, sub, action, tool, no_order_only, bases)
    """
    category, main, sub, action, tool, no_order_only, bases = spec
    cases: list[dict] = []

    for base in bases:
        if no_order_only:
            # 不带订单号（问候/超出/投诉/澄清/退咨无单）
            for prefix in PREFIXES:
                msg = _norm(f"{prefix}{base}")
                if msg:
                    cases.append(_make_case(category, main, sub, action, tool, msg, base,
                                            oid=None))
        else:
            # 带订单号：订单/物流/退款/退咨带单
            id_pool = LOGISTICS_IDS if category == "logistics" else ORDER_IDS
            for oid in id_pool:
                for variant in _order_id_variants(base, oid):
                    for prefix in PREFIXES:
                        msg = _norm(f"{prefix}{variant}")
                        if msg:
                            cases.append(_make_case(category, main, sub, action, tool, msg,
                                                    base, oid=oid))
    return cases


def _make_case(category, main, sub, action, tool, message, base, oid) -> dict:
    ref_reply, must_contain, rubric = _reference_for(category, main, sub, oid, base)
    return {
        "category": category,
        "inputs": {"message": message},  # session_id 在生成阶段统一补
        "outputs": {
            "expected_main_intent": main,
            "expected_sub_intent": sub,
            "expected_action": action,
            "expected_tool": tool,
            "reference_reply": ref_reply,
            "must_contain": must_contain,
            "rubric": rubric,
        },
    }


def _reference_for(category, main, sub, oid, base) -> tuple[str, list[str], str]:
    """构造理想回复、必含事实点、评分要点。"""
    if category == "order_query" and oid:
        o = KNOWN_ORDERS[oid]
        reply = (f"订单 {oid} 当前状态为{o['status']}，"
                 f"商品是{o['product_name']}，金额{_fmt_amount(o['amount'])}元。")
        return reply, [oid, o["status"], o["product_name"]], \
            "应准确返回订单状态、商品名称与金额，语气友好专业。"

    if category == "logistics" and oid:
        o = KNOWN_ORDERS[oid]
        lg = o["logistics"]
        reply = (f"订单 {oid} 当前物流状态为{lg['tracking_status']}，"
                 f"最近一条记录是{lg['latest']}。")
        return reply, [oid, lg["tracking_status"]], \
            "应返回物流轨迹状态，必要时提示最新进展。"

    if category == "refund_request":
        reply = ("已收到您的退款申请，我们会尽快为您处理，退款将原路返回，"
                 "请留意到账通知。")
        return reply, ["退款", "受理"], \
            "应确认受理退款诉求，并说明退款退回方式。"

    if category == "refund_consult":
        if oid:
            reply = ("关于退款：商品签收后 7 天内可申请无理由退货退款，退款将原路退回，"
                     "到账时间以支付渠道为准。已为您记下订单号，可继续为您核实。")
            return reply, ["退款", "七天", "原路"], \
                "应说明退款政策要点（七天无理由、原路退回），并基于已有订单号处理。"
        reply = "关于退款：商品签收后 7 天内可申请无理由退货退款，退款将原路退回。"
        return reply, ["退款", "七天"], \
            "应说明退款政策要点。"

    if category == "refund_consult_clarify":
        reply = ("关于退款：商品签收后 7 天内可申请无理由退货退款，退款将原路退回，"
                 "到账时间以支付渠道为准。如需我为您核实具体订单，请提供订单号。")
        return reply, ["退款", "七天"], \
            "应说明退款政策要点（七天无理由、原路退回）；缺订单号时引导用户提供，但不臆测。"

    if category == "handoff":
        reply = "已为您转接人工客服，稍后会有专人为您服务（服务单号 Hxxxx）。"
        return reply, ["人工", "服务单号"], \
            "应明确告知已转人工，并给出服务单号。"

    if category == "greeting":
        reply = ("你好！我是您的智能客服助手，可以帮您查询订单、物流，"
                 "处理退款售后，也可以为您转接人工客服～")
        return reply, ["订单", "物流", "退款"], \
            "应友好问候，并说明可提供的服务能力（订单/物流/退款/转人工）。"

    if category == "unsupported":
        reply = "这个问题超出了我的服务范围，建议您联系对应部门或拨打官方客服热线咨询哦。"
        return reply, ["服务范围"], \
            "应说明超出服务范围，并引导至合适渠道，不编造答案。"

    if category == "complaint":
        reply = "非常抱歉给您带来了不好的体验，我已记录您的问题，会尽快为您跟进处理。"
        return reply, ["抱歉"], \
            "应共情致歉，表明已记录并会跟进，不推诿。"

    if category == "clarify_no_id":
        reply = "为了帮您查询，请提供一下订单号哦～"
        return reply, ["订单号"], \
            "应追问订单号以补全信息。"

    # fallback
    return "", [], "通用回复。"


def _build_multiturn() -> list[dict]:
    """多轮跟进：带 previous_sub_intent + 订单号，gold = 上一轮子意图（slot_followup）。"""
    specs = [
        ("order_query", "order_query.query_status", "order_query", "order_query.query_status",
         "agent_process", "order_query"),
        ("logistics", "logistics.not_received", "logistics", "logistics.not_received",
         "agent_process", "logistics"),
        ("refund_request", "after_sale_refund.request_refund", "after_sale_refund",
         "after_sale_refund.request_refund", "agent_process", "aftersale_refund"),
    ]
    templates = ["{oid}", "帮我催一下 {oid}", "{oid} 怎么样了", "再等等 {oid}", "继续处理 {oid}"]
    cases: list[dict] = []
    for main, sub, exp_main, exp_sub, action, tool in specs:
        oid_pool = LOGISTICS_IDS if tool == "logistics" else ORDER_IDS
        for oid in oid_pool:
            for tmpl in templates:
                msg = _norm(tmpl.format(oid=oid))
                ref_reply, must_contain, rubric = _reference_for(
                    "order_query" if tool == "order_query" else
                    ("logistics" if tool == "logistics" else "refund_request"),
                    exp_main, exp_sub, oid, msg,
                )
                cases.append({
                    "category": "multiturn_followup",
                    "inputs": {"message": msg, "previous_sub_intent": sub},
                    "outputs": {
                        "expected_main_intent": exp_main,
                        "expected_sub_intent": exp_sub,
                        "expected_action": action,
                        "expected_tool": tool,
                        "reference_reply": ref_reply,
                        "must_contain": must_contain,
                        "rubric": "应基于上一轮上下文（slot_followup）继续处理，无需重新识别意图。",
                    },
                })
    return cases


def generate(target: int | None = None) -> list[dict]:
    random.seed(20240712)
    specs = [
        ORDER_QUERY, LOGISTICS, REFUND_REQUEST, REFUND_CONSULT_WITH_ID,
        REFUND_CONSULT_NO_ID, HANDOFF, GREETING, UNSUPPORTED, COMPLAINT, CLARIFY_NO_ID,
    ]
    cases: list[dict] = []
    for spec in specs:
        cases.extend(_build_category(spec))
    cases.extend(_build_multiturn())

    # 去重（同 message + 同上下文视为重复）
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for c in cases:
        key = (c["inputs"]["message"], c["inputs"].get("previous_sub_intent", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)

    # 目标数量：超出则按类别抽样至 target，但保证各类别最小覆盖
    if target and len(unique) > target:
        from collections import Counter
        by_cat: dict[str, list[dict]] = {}
        for c in unique:
            by_cat.setdefault(c["category"], []).append(c)
        # 各类最小保底（多轮跟进较珍贵）
        min_floor = {
            "multiturn_followup": 40,
            "handoff": 40,
            "greeting": 40,
            "unsupported": 30,
            "complaint": 30,
            "clarify_no_id": 40,
            "refund_consult_clarify": 40,
        }
        keep: list[dict] = []
        quota = target
        for cat, items in by_cat.items():
            floor = min(min_floor.get(cat, 30), len(items))
            keep.extend(random.sample(items, floor))
            quota -= floor
        rest_cats = {cat: items for cat, items in by_cat.items()
                     if len(items) > min_floor.get(cat, 30)}
        rest_pool = [c for items in rest_cats.values() for c in items]
        if rest_pool and quota > 0:
            keep.extend(random.sample(rest_pool, min(quota, len(rest_pool))))
        unique = keep

    # 赋 id + 唯一 session_id，并打散
    random.shuffle(unique)
    for i, c in enumerate(unique, 1):
        c["id"] = f"ans_{i:04d}"
        c["inputs"]["session_id"] = f"ans-sess-{i:05d}"
    return unique


def main() -> None:
    parser = argparse.ArgumentParser(description="生成最终回复评估测试集")
    parser.add_argument("--count", type=int, default=1000, help="目标样本数（默认 1000）")
    args = parser.parse_args()

    cases = generate(target=args.count)

    out_path = Path(__file__).resolve().parent / "answer_eval_cases.json"
    backup = out_path.with_suffix(".json.bak")
    if out_path.exists():
        out_path.replace(backup)
        print(f"[BACKUP] 旧测试集已备份到 {backup.name}")

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

    from collections import Counter
    cat_counter = Counter(c["category"] for c in cases)
    intent_counter = Counter(c["outputs"]["expected_main_intent"] for c in cases)
    action_counter = Counter(c["outputs"]["expected_action"] for c in cases)
    print(f"[OK] 已生成 {len(cases)} 条样本 -> {out_path.name}")
    print("  按类别：")
    for k, v in cat_counter.most_common():
        print(f"    - {k}: {v}")
    print("  按动作：")
    for k, v in action_counter.most_common():
        print(f"    - {k}: {v}")
    print("  按主意图：")
    for k, v in intent_counter.most_common():
        print(f"    - {k}: {v}")


if __name__ == "__main__":
    main()
