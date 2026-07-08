from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVAL_DIR = ROOT / "eval"
CASES_PATH = EVAL_DIR / "intent_single_step_cases.json"


def load_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def evaluate(use_llm: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.models import ConversationState
    from app.services.routing import IntentRouterService

    cases = load_json(CASES_PATH)
    results: list[dict[str, Any]] = []
    main_intent_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "matched": 0}
    )
    route_counter: Counter[str] = Counter()

    router = IntentRouterService.from_env(use_llm=use_llm)

    for case in cases:
        state = ConversationState(session_id="eval", user_id="eval", channel="eval")
        actual = router.route(state, case["message"])

        matched = (
            actual.main_intent == case["expected_main_intent"]
            and actual.sub_intent == case["expected_sub_intent"]
        )
        route_counter[actual.route_source] += 1
        main_intent_stats[case["expected_main_intent"]]["total"] += 1
        if matched:
            main_intent_stats[case["expected_main_intent"]]["matched"] += 1

        results.append(
            {
                **case,
                "actual_main_intent": actual.main_intent,
                "actual_sub_intent": actual.sub_intent,
                "route_source": actual.route_source,
                "confidence": actual.confidence,
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


def write_outputs(
    results: list[dict[str, Any]],
    metrics: dict[str, Any],
    tag: str,
) -> None:
    results_path = EVAL_DIR / f"intent_single_step_results_{tag}.json"
    report_path = EVAL_DIR / f"intent_single_step_report_{tag}.md"

    with results_path.open("w", encoding="utf-8") as file:
        json.dump({"metrics": metrics, "results": results}, file, ensure_ascii=False, indent=2)

    failed_lines = []
    for item in metrics["failed_cases"]:
        failed_lines.append(
            f"- `{item['id']}`: `{item['message']}` "
            f"-> expected `{item['expected_main_intent']} / {item['expected_sub_intent']}`, "
            f"actual `{item['actual_main_intent']} / {item['actual_sub_intent']}` "
            f"(source={item.get('route_source', 'N/A')})"
        )

    per_intent_lines = []
    for intent, values in metrics["per_main_intent"].items():
        per_intent_lines.append(
            f"- `{intent}`: {values['matched']} / {values['total']} = {values['accuracy']:.2%}"
        )

    route_lines = [
        f"  - `{k}`: {v}" for k, v in metrics["route_source_distribution"].items()
    ]

    mode_label = "规则 + LLM 兜底" if tag == "with_llm" else "纯规则（无 LLM）"

    report = "\n".join(
        [
            f"# 意图识别单点评估报告（{mode_label}）",
            "",
            "## 评估方式",
            "",
            f"评估 `IntentRouterService` 的{'完整' if tag == 'with_llm' else '规则-only'}路由链路。",
            "",
            "## 总体结果",
            "",
            f"- 样本总数：{metrics['total_cases']}",
            f"- 命中样本：{metrics['matched_cases']}",
            f"- 准确率：{metrics['accuracy']:.2%}",
            f"- 路由来源分布：",
            *route_lines,
            "",
            "## 按主意图统计",
            "",
            *per_intent_lines,
            "",
            "## 未覆盖/误判样本",
            "",
            *(failed_lines or ["- 无"]),
            "",
        ]
    )

    with report_path.open("w", encoding="utf-8") as file:
        file.write(report + "\n")


if __name__ == "__main__":
    tag = "with_llm"
    use_llm = True
    if "--no-llm" in sys.argv:
        tag = "no_llm"
        use_llm = False

    print(f"评估模式：{'规则 + LLM 兜底' if use_llm else '纯规则'}")
    results_data, metrics_data = evaluate(use_llm=use_llm)
    write_outputs(results_data, metrics_data, tag=tag)
    print(json.dumps(metrics_data, ensure_ascii=False, indent=2))
    print(f"\n结果已写入 eval/intent_single_step_*_{tag}.*")
