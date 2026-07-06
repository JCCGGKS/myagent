from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "eval"
FAQ_PATH = ROOT / "app" / "mock_data" / "faqs.json"
CASES_PATH = EVAL_DIR / "intent_single_step_cases.json"
RESULTS_PATH = EVAL_DIR / "intent_single_step_results.json"
REPORT_PATH = EVAL_DIR / "intent_single_step_report.md"


def load_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


FAQ_ITEMS = load_json(FAQ_PATH)


def extract_order_id(text: str) -> str | None:
    upper = text.upper()
    for token in upper.replace("，", " ").replace(",", " ").split():
        if len(token) == 5 and token[0].isalpha() and token[1:].isdigit():
            return token
    return None


def search_faq(query: str) -> dict[str, Any] | None:
    normalized = query.casefold()
    for item in FAQ_ITEMS:
        for question in item["questions"]:
            question_normalized = question.casefold()
            if question_normalized in normalized or normalized in question_normalized:
                return item
        keyword_hits = 0
        for keyword in item["keywords"]:
            if keyword.casefold() in normalized:
                keyword_hits += 1
        if keyword_hits >= 2:
            return item
    return None


def classify_rule_only(message: str, previous_sub_intent: str = "unsupported.unknown") -> dict[str, Any]:
    lowered = message.casefold()
    order_id = extract_order_id(message)
    faq = search_faq(message)

    has_handoff_keyword = any(token in lowered for token in ["转人工", "人工客服"])
    has_logistics_keyword = any(token in lowered for token in ["物流", "快递", "配送"])
    has_order_keyword = any(
        token in lowered for token in ["查订单", "订单", "订单状态", "发货了吗", "我的订单"]
    )
    has_refund_keyword = "退款" in lowered
    has_refund_rule_keyword = any(token in lowered for token in ["规则", "退吗", "可以退款", "怎么处理"])
    has_refund_action_keyword = any(token in lowered for token in ["我要退款", "申请退款", "帮我退款"])
    has_greeting_keyword = any(
        token in lowered for token in ["你好", "您好", "hi", "hello", "在吗"]
    )
    has_thanks_keyword = any(
        token in lowered for token in ["谢谢", "感谢", "辛苦了", "thanks", "thank you"]
    )

    if has_handoff_keyword:
        return {
            "main_intent": "handoff_service",
            "sub_intent": "handoff_service.request_human",
            "route_source": "rule",
        }
    if has_logistics_keyword:
        return {
            "main_intent": "logistics_service",
            "sub_intent": "logistics_service.query_status",
            "route_source": "rule",
        }
    if has_greeting_keyword:
        return {
            "main_intent": "chitchat",
            "sub_intent": "chitchat.greeting",
            "route_source": "rule",
        }
    if has_thanks_keyword:
        return {
            "main_intent": "chitchat",
            "sub_intent": "chitchat.thanks",
            "route_source": "rule",
        }
    if has_order_keyword:
        return {
            "main_intent": "order_service",
            "sub_intent": "order_service.query_status",
            "route_source": "rule",
        }
    if order_id and previous_sub_intent in {
        "order_service.query_status",
        "logistics_service.query_status",
    }:
        main_intent = (
            "order_service"
            if previous_sub_intent == "order_service.query_status"
            else "logistics_service"
        )
        return {
            "main_intent": main_intent,
            "sub_intent": previous_sub_intent,
            "route_source": "slot_followup",
        }
    if has_refund_keyword and (has_refund_rule_keyword or has_refund_action_keyword or "到账" not in lowered):
        return {
            "main_intent": "unsupported",
            "sub_intent": "unsupported.unknown",
            "route_source": "rule",
        }
    if faq:
        return {
            "main_intent": "faq",
            "sub_intent": "faq.general",
            "route_source": "rule",
        }
    return {
        "main_intent": "unsupported",
        "sub_intent": "unsupported.unknown",
        "route_source": "fallback",
    }


def evaluate() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases = load_json(CASES_PATH)
    results: list[dict[str, Any]] = []
    main_intent_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "matched": 0}
    )
    route_counter: Counter[str] = Counter()

    for case in cases:
        actual = classify_rule_only(case["message"], case.get("previous_sub_intent", "unsupported.unknown"))
        matched = (
            actual["main_intent"] == case["expected_main_intent"]
            and actual["sub_intent"] == case["expected_sub_intent"]
        )
        route_counter[actual["route_source"]] += 1
        main_intent_stats[case["expected_main_intent"]]["total"] += 1
        if matched:
            main_intent_stats[case["expected_main_intent"]]["matched"] += 1

        results.append(
            {
                **case,
                "actual_main_intent": actual["main_intent"],
                "actual_sub_intent": actual["sub_intent"],
                "route_source": actual["route_source"],
                "matched": matched,
            }
        )

    total = len(results)
    matched_total = sum(1 for item in results if item["matched"])
    metrics = {
        "total_cases": total,
        "matched_cases": matched_total,
        "accuracy": round(matched_total / total, 4) if total else 0.0,
        "route_source_distribution": dict(route_counter),
        "per_main_intent": {
            intent: {
                "total": values["total"],
                "matched": values["matched"],
                "accuracy": round(values["matched"] / values["total"], 4) if values["total"] else 0.0,
            }
            for intent, values in sorted(main_intent_stats.items())
        },
        "failed_cases": [item for item in results if not item["matched"]],
    }
    return results, metrics


def write_outputs(results: list[dict[str, Any]], metrics: dict[str, Any]) -> None:
    with RESULTS_PATH.open("w", encoding="utf-8") as file:
        json.dump({"metrics": metrics, "results": results}, file, ensure_ascii=False, indent=2)

    failed_lines = []
    for item in metrics["failed_cases"]:
        failed_lines.append(
            f"- `{item['id']}`: `{item['message']}` -> expected `{item['expected_main_intent']} / {item['expected_sub_intent']}`,"
            f" actual `{item['actual_main_intent']} / {item['actual_sub_intent']}`"
        )

    per_intent_lines = []
    for intent, values in metrics["per_main_intent"].items():
        per_intent_lines.append(
            f"- `{intent}`: {values['matched']} / {values['total']} = {values['accuracy']:.2%}"
        )

    report = "\n".join(
        [
            "# 意图识别单点评估报告",
            "",
            "## 评估方式",
            "",
            "参考 LangSmith `evaluate-complex-agent` 中的 single-step evaluation 思路，本次只评估“意图识别节点”本身，不评估回复生成、工具调用和多步轨迹。",
            "",
            "当前被评估方案为“纯规则匹配”：",
            "",
            "- 意图路由只依赖显式关键词规则",
            "- FAQ 命中只依赖 `faqs.json` 中的关键词和问题短语包含匹配",
            "- 保留订单号补槽位续接规则",
            "- 不包含相似度、向量检索或 LLM 判断",
            "",
            "## 总体结果",
            "",
            f"- 样本总数：{metrics['total_cases']}",
            f"- 命中样本：{metrics['matched_cases']}",
            f"- 准确率：{metrics['accuracy']:.2%}",
            f"- 路由来源分布：{json.dumps(metrics['route_source_distribution'], ensure_ascii=False)}",
            "",
            "## 按主意图统计",
            "",
            *per_intent_lines,
            "",
            "## 未覆盖/误判样本",
            "",
            *(failed_lines or ["- 无"]),
            "",
            "## 结论",
            "",
            "规则匹配可以稳定覆盖显式表达、短句、固定问法和少量多轮补槽位，但对口语化变体、售后动作类请求、账户类请求和同义表达覆盖仍然有限。",
            "",
            "## 是否建议引入第二层相似度检索",
            "",
            "当前更建议先继续收紧规则层，再决定是否引入第二层相似度检索。",
            "",
            "原因：",
            "",
            "- 如果失败样本主要是显式边界冲突，例如 FAQ 吞掉订单/退款动作，应优先改规则",
            "- 如果失败样本主要变成同义表达、口语化和轻省略表达，再考虑加第二层相似度检索",
            "",
            "下一步如果继续做单点评估，建议按下面三类扩样本：",
            "",
            "- 同义表达：例如 `什么时候能收到货`、`帮我看下快递到哪`、`包裹在哪`",
            "- 新业务域：例如退款申请、投诉、优惠券、发票修改",
            "- 多轮补充：例如上一轮查订单、下一轮只回复订单号或手机号",
            "",
        ]
    )

    with REPORT_PATH.open("w", encoding="utf-8") as file:
        file.write(report + "\n")


if __name__ == "__main__":
    results_data, metrics_data = evaluate()
    write_outputs(results_data, metrics_data)
    print(json.dumps(metrics_data, ensure_ascii=False, indent=2))
