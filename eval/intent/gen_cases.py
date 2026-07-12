"""意图识别评估测试集生成器。

重新生成 ``intent_single_step_cases.json``，使其与当前生产意图空间
（``app/schema/intent.py`` 的 ``MAIN_INTENT_CODES`` / ``SUB_INTENT_CODES``）
严格对齐。

设计原则：
- 金标（expected）按「系统规范映射」给出：规则层能产出的子意图按规则；
  LLM 兜底层才区分的细分子意图（modify_address / apply_invoice / lost_package /
  delayed / damage_refund / no_reason_return / wrong_goods / compensate）按 LLM 规范。
- 覆盖四类样本，使「规则-only vs 规则+LLM」对比有真实差异：
  1) 规则命中（两者都应命中）
  2) 规则给粗/给错子意图、LLM 应给细子意图（仅 +LLM 命中）
  3) 口语/省略（无规则关键词，需 LLM 兜底）（仅 +LLM 命中）
  4) 多轮跟进（带 previous_sub_intent，两者都应命中）
  5) 未识别 / 超出业务范围（两者都应命中）

用法：
  python3 eval/intent/gen_cases.py            # 重新生成（覆盖）测试集
  python3 eval/intent/gen_cases.py --count N  # 目标样本数（默认尽量贴近 1000）
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
OUT_PATH = EVAL_DIR / "intent_single_step_cases.json"
BACKUP_PATH = EVAL_DIR / "intent_single_step_cases.json.bak"

# 与 routing.py 的 _SLOT_FOLLOWUP_SUB_INTENTS 对齐
FOLLOWUP_SUBS = [
    "order_query.query_status",
    "logistics.not_received",
    "after_sale_refund.request_refund",
    "after_sale_refund.consult_policy",
]

ORDER_IDS = ["A1001", "B6688", "C3090", "D7721", "E4455"]
# 仅使用不会拼接出「action 关键词 / 其它意图关键词」的安全前缀：
# 去掉「帮我」「我要」——它们与「退款」等拼接会形成 after_sale 的 action 关键词，
# 导致规则层把 consult_policy 误判为 request_refund。
PREFIXES = ["", "麻烦", "请问", "我想"]

# 需要订单号的意图（生成时注入订单号变体）
ORDER_INTENTS = {
    "order_query",
    "logistics",
    "after_sale_refund",
}


def _norm(text: str) -> str:
    """去掉首尾空白与多余空格。"""
    return " ".join(text.split()).strip()


# =========================================================================
# 各类样本定义：(gold_main, gold_sub, [基础表达列表], 是否允许多轮)
# =========================================================================

# 1) 规则命中：规则关键词直接命中，gold = 规则默认/action 子意图
RULE_HIT = [
    ("order_query", "order_query.query_status", [
        "查订单", "订单状态", "我的订单", "我的单", "查单", "发货了吗", "订单", "订单详情",
    ]),
    ("logistics", "logistics.not_received", [
        "物流", "快递", "配送", "到哪了", "到哪儿了", "什么时候到", "没收到", "签收", "派送",
    ]),
    ("after_sale_refund", "after_sale_refund.consult_policy", [
        "退款", "退货", "售后", "退换", "换货", "退货退款",
        "不想要了", "不想要", "不要了", "质量", "坏了", "质量问题",
    ]),
    ("after_sale_refund", "after_sale_refund.request_refund", [
        "我要退款", "申请退款", "帮我退款",
    ]),
    ("handoff_service", "handoff_service.request_human", [
        "转人工", "人工客服", "找人工", "人工", "真人", "客服",
    ]),
    ("complaint", "complaint.service_complaint", [
        "投诉", "差评", "太差了", "不处理",
        "没用", "气死", "受不了", "12315", "消费者协会",
    ]),
]

# 2) 规则给粗/给错子意图，LLM 应给细子意图（仅 +LLM 命中）
#    a) 规则层映射到的缺省子意图过粗，LLM 能区分细子意图
#    b) action-only 短语（无 base 关键词）规则层根本不命中，仅 LLM 能识别
FINER_SUBINTENT = [
    ("order_query", "order_query.modify_address", ["改地址", "修改地址"]),
    ("order_query", "order_query.apply_invoice", ["开发票"]),
    ("logistics", "logistics.lost_package", ["丢件", "包裹丢了"]),
    ("logistics", "logistics.delayed", ["快递延迟了", "物流更新很慢"]),
    ("after_sale_refund", "after_sale_refund.damage_refund", ["商品损坏了要退款", "收到的东西坏了"]),
    ("after_sale_refund", "after_sale_refund.no_reason_return", ["七天无理由退货", "不想要了想退"]),
    ("after_sale_refund", "after_sale_refund.wrong_goods", ["收到错货了", "发错货了"]),
    ("after_sale_refund", "after_sale_refund.request_refund", ["直接退", "帮退一下", "退掉"]),
    ("complaint", "complaint.compensate", ["赔偿", "赔付"]),
]

# 3) 口语/省略：无规则关键词，需 LLM 兜底（仅 +LLM 命中）
COLLOQUIAL = [
    ("logistics", "logistics.not_received", [
        "我的东西发出来没有", "啥时候能送过来", "货到没到啊", "我的包裹还在路上吗", "买的东西一直没动静",
    ]),
    ("order_query", "order_query.query_status", [
        "看下我拍下的", "帮查下我买的东西", "我想知道我下的单咋样了", "查一下我买的",
    ]),
    ("after_sale_refund", "after_sale_refund.request_refund", [
        "买的东西想退", "东西有问题想退", "这单我后悔了", "申请把买的退了",
    ]),
    ("after_sale_refund", "after_sale_refund.consult_policy", [
        "收到的货有点问题",
    ]),
    ("complaint", "complaint.service_complaint", [
        "这体验太烂了", "你们这态度我真服了", "越想越气", "太让人失望了",
    ]),
    ("handoff_service", "handoff_service.request_human", [
        "我要跟人说话", "别跟机器人说了", "我要找活人",
    ]),
    ("unsupported_biz", "unsupported_biz.out_of_scope", [
        "你们招人吗", "我想应聘", "你们有代理吗", "怎么加盟你们",
    ]),
]

# 5) 未识别 / 超出业务范围（两者都应命中）
UNRECOGNIZE = [
    ("unrecognize", "unrecognize.unknown", [
        "你好", "在吗", "hello", "嗨", "在不在", "有人吗", "今天天气真好", "随便聊聊", "在么",
    ]),
]


def _expand(main: str, sub: str, bases: list[str], category: str) -> list[dict]:
    """把基础表达展开为多条样本（注入前缀 / 订单号变体）。"""
    cases: list[dict] = []
    needs_order = main in ORDER_INTENTS
    for base in bases:
        # 无订单号变体
        for prefix in PREFIXES:
            msg = _norm(f"{prefix}{base}")
            if msg:
                cases.append({"message": msg, "expected_main_intent": main,
                              "expected_sub_intent": sub, "category": category})
        # 订单号变体（仅订单类意图）
        if needs_order:
            for prefix in PREFIXES:
                for oid in ORDER_IDS:
                    variants = [
                        f"{prefix}{base}，单号{oid}",
                        f"单号{oid}，{prefix}{base}",
                    ]
                    for v in variants:
                        msg = _norm(v)
                        if msg:
                            cases.append({"message": msg, "expected_main_intent": main,
                                          "expected_sub_intent": sub, "category": category})
    return cases


def _build_followups() -> list[dict]:
    """多轮跟进样本：带 previous_sub_intent，gold = 上一轮子意图。"""
    cases: list[dict] = []
    templates = ["{oid}", "帮我催一下 {oid}", "{oid} 怎么样了", "再等等 {oid}"]
    for sub in FOLLOWUP_SUBS:
        for tmpl in templates:
            for oid in ORDER_IDS:
                msg = _norm(tmpl.format(oid=oid))
                cases.append({
                    "message": msg,
                    "expected_main_intent": sub.split(".", 1)[0],
                    "expected_sub_intent": sub,
                    "previous_sub_intent": sub,
                    "category": "multiturn_followup",
                })
    return cases


def generate(target: int | None = None) -> list[dict]:
    random.seed(20240712)
    cases: list[dict] = []
    for main, sub, bases in RULE_HIT:
        cases.extend(_expand(main, sub, bases, "rule_hit"))
    for main, sub, bases in FINER_SUBINTENT:
        cases.extend(_expand(main, sub, bases, "finer_subintent"))
    for main, sub, bases in COLLOQUIAL:
        cases.extend(_expand(main, sub, bases, "colloquial"))
    for main, sub, bases in UNRECOGNIZE:
        cases.extend(_expand(main, sub, bases, "unrecognize"))
    cases.extend(_build_followups())

    # 去重（同 message + 同上一轮子意图 视为重复；多轮跟进的相同消息但不同上下文是不同用例）
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for c in cases:
        key = (c["message"], c.get("previous_sub_intent", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)

    # 目标数量：若超出则按类别抽样至 target，但保证重点类别的最小覆盖
    if target and len(unique) > target:
        by_cat: dict[str, list[dict]] = {}
        for c in unique:
            by_cat.setdefault(c["category"], []).append(c)
        # 各类最小保留数（多轮跟进样本较珍贵，给予更高保底）
        min_floor = {
            "multiturn_followup": 40,
            "unrecognize": 20,
            "rule_hit": 0,
            "colloquial": 0,
            "finer_subintent": 0,
        }
        keep: list[dict] = []
        quota = target
        for cat, items in by_cat.items():
            floor = min(min_floor.get(cat, 5), len(items))
            keep.extend(random.sample(items, floor))
            quota -= floor
        rest_cats = {cat: items for cat, items in by_cat.items()
                     if len(items) > min_floor.get(cat, 5)}
        rest_pool = [c for items in rest_cats.values() for c in items]
        if rest_pool and quota > 0:
            keep.extend(random.sample(rest_pool, min(quota, len(rest_pool))))
        unique = keep

    # 赋 id 并打散
    random.shuffle(unique)
    for i, c in enumerate(unique, 1):
        c["id"] = f"case_{i:04d}"
    return unique


def main() -> None:
    parser = argparse.ArgumentParser(description="生成意图识别评估测试集")
    parser.add_argument("--count", type=int, default=1000, help="目标样本数（默认 1000）")
    args = parser.parse_args()

    cases = generate(target=args.count)

    if OUT_PATH.exists():
        OUT_PATH.replace(BACKUP_PATH)
        print(f"[BACKUP] 旧测试集已备份到 {BACKUP_PATH.name}")

    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

    # 统计
    from collections import Counter
    cat_counter = Counter(c["category"] for c in cases)
    intent_counter = Counter(c["expected_main_intent"] for c in cases)
    print(f"[OK] 已生成 {len(cases)} 条样本 -> {OUT_PATH.name}")
    print("  按类别：")
    for k, v in cat_counter.most_common():
        print(f"    - {k}: {v}")
    print("  按主意图：")
    for k, v in intent_counter.most_common():
        print(f"    - {k}: {v}")


if __name__ == "__main__":
    main()
