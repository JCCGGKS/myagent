from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from run_intent_single_step_eval import (  # type: ignore
    CASES_PATH,
    EVAL_DIR,
    classify_rule_only,
    evaluate as evaluate_rule_only,
    load_json,
)


COMPARE_RESULTS_PATH = EVAL_DIR / "intent_compare_results.json"
COMPARE_REPORT_PATH = EVAL_DIR / "intent_compare_report.md"


def classify_rule_plus_llm(
    message: str,
    previous_sub_intent: str = "unsupported.unknown",
) -> tuple[dict[str, Any], str | None, dict[str, Any] | None]:
    rule_result = classify_rule_only(message, previous_sub_intent)

    if rule_result["route_source"] != "fallback":
        return rule_result, None, None

    try:
        from app.config import load_llm_config
        from app.services import LLMIntentFallbackService
    except Exception as exc:
        return rule_result, f"llm_import_unavailable: {exc!r}", None

    config = load_llm_config()
    llm_service = LLMIntentFallbackService(config)

    if not llm_service.enabled:
        return rule_result, "llm_not_enabled_or_not_usable", llm_service.last_debug

    llm_result = llm_service.classify(message, previous_sub_intent)
    if llm_result is None:
        return rule_result, "llm_no_result", llm_service.last_debug

    return (
        {
            "main_intent": llm_result.main_intent,
            "sub_intent": llm_result.sub_intent,
            "route_source": llm_result.route_source,
        },
        None,
        llm_service.last_debug,
    )


def evaluate_rule_plus_llm() -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    cases = load_json(CASES_PATH)
    results: list[dict[str, Any]] = []
    llm_skip_reason: str | None = None

    matched_cases = 0
    llm_hits = 0
    llm_debug_samples: list[dict[str, Any]] = []

    for case in cases:
        actual, skip_reason, llm_debug = classify_rule_plus_llm(
            case["message"], case.get("previous_sub_intent", "unsupported.unknown")
        )
        if skip_reason and llm_skip_reason is None:
            if llm_debug and llm_debug.get("status"):
                llm_skip_reason = f"{skip_reason}:{llm_debug.get('status')}:{llm_debug.get('error', '')}"
            else:
                llm_skip_reason = skip_reason
        if llm_debug is not None:
            llm_debug_samples.append(
                {
                    "id": case["id"],
                    "message": case["message"],
                    "debug": llm_debug,
                }
            )

        matched = (
            actual["main_intent"] == case["expected_main_intent"]
            and actual["sub_intent"] == case["expected_sub_intent"]
        )
        if matched:
            matched_cases += 1
        if actual["route_source"] == "llm_fallback":
            llm_hits += 1

        results.append(
            {
                **case,
                "actual_main_intent": actual["main_intent"],
                "actual_sub_intent": actual["sub_intent"],
                "route_source": actual["route_source"],
                "matched": matched,
            }
        )

    total_cases = len(results)
    metrics = {
        "total_cases": total_cases,
        "matched_cases": matched_cases,
        "accuracy": round(matched_cases / total_cases, 4) if total_cases else 0.0,
        "llm_fallback_hits": llm_hits,
        "failed_cases": [item for item in results if not item["matched"]],
        "llm_debug_samples": llm_debug_samples,
    }
    return results, metrics, llm_skip_reason


def write_compare_outputs(
    rule_metrics: dict[str, Any],
    llm_metrics: dict[str, Any] | None,
    llm_skip_reason: str | None,
    llm_results: list[dict[str, Any]] | None,
) -> None:
    payload = {
        "rule_only": rule_metrics,
        "rule_plus_llm": llm_metrics,
        "llm_skip_reason": llm_skip_reason,
        "llm_results": llm_results,
    }
    with COMPARE_RESULTS_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    lines = [
        "# 规则 Only vs 规则+LLM 对比评估",
        "",
        "## 说明",
        "",
        "- `规则-only`：只运行当前显式规则和 FAQ 规则",
        "- `规则+LLM`：先运行规则；当规则结果落到 `fallback` 时，再尝试调用 LLM 兜底",
        "- 当前对比不会覆盖规则直接返回 `unsupported` 但未进入 `fallback` 的样本，这与现有后端实现保持一致",
        "",
        "## 规则-only",
        "",
        f"- 样本总数：{rule_metrics['total_cases']}",
        f"- 命中样本：{rule_metrics['matched_cases']}",
        f"- 准确率：{rule_metrics['accuracy']:.2%}",
        "",
    ]

    if llm_metrics is None:
        diagnostic_lines = [
            "当前无法得到有效的 `规则+LLM` 对比结果。"
        ]
        if llm_skip_reason == "llm_no_result":
            diagnostic_lines.extend(
                [
                    "当前环境里的 LLM fallback 已尝试调用，但没有拿到可解析的结构化结果。",
                    "这通常意味着中转站/模型对当前 API 形态或 JSON 输出约束不兼容。",
                ]
            )
        else:
            diagnostic_lines.append(
                "要生成对比结果，需要安装依赖并在本地可用配置中启用 LLM fallback。"
            )
        lines.extend(
            [
                "## 规则+LLM",
                "",
                "- 本次未执行",
                f"- 原因：`{llm_skip_reason or 'unknown'}`",
                "",
                "## 结论",
                "",
                *diagnostic_lines,
                "",
                "建议检查：",
                "",
                "- 是否已安装 `openai`、`pydantic` 等依赖",
                "- `config/llm_config.local.json` 是否存在且 `enabled=true`",
                "- `api_key`、`base_url`、`model` 是否可用",
                "- 中转站是否兼容 `responses.parse` 或 `chat.completions` 的 JSON 结构化输出",
                "",
            ]
        )
    else:
        delta = llm_metrics["matched_cases"] - rule_metrics["matched_cases"]
        accuracy_delta = llm_metrics["accuracy"] - rule_metrics["accuracy"]
        failed_lines = [
            f"- `{item['id']}`: `{item['message']}` -> expected `{item['expected_main_intent']} / {item['expected_sub_intent']}`, actual `{item['actual_main_intent']} / {item['actual_sub_intent']}`"
            for item in llm_metrics["failed_cases"]
        ]
        lines.extend(
            [
                "## 规则+LLM",
                "",
                f"- 样本总数：{llm_metrics['total_cases']}",
                f"- 命中样本：{llm_metrics['matched_cases']}",
                f"- 准确率：{llm_metrics['accuracy']:.2%}",
                f"- LLM 兜底命中次数：{llm_metrics['llm_fallback_hits']}",
                "",
                "## 差异",
                "",
                f"- 命中数变化：{delta:+d}",
                f"- 准确率变化：{accuracy_delta:+.2%}",
                "",
                "## 规则+LLM 未命中样本",
                "",
                *(failed_lines or ["- 无"]),
                "",
                "## LLM 调试样本",
                "",
                *[
                    f"- `{item['id']}`: `{item['debug'].get('status', 'unknown')}`"
                    for item in llm_metrics.get("llm_debug_samples", [])[:8]
                ],
                "",
                "## 结论",
                "",
                "如果 `规则+LLM` 只提升极少量样本，说明当前更应该继续优化规则层。"
                "如果它主要修复了口语化、同义表达和轻省略表达，则可以考虑保留为二级兜底。",
                "",
            ]
        )

    with COMPARE_REPORT_PATH.open("w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    _, rule_metrics = evaluate_rule_only()
    llm_results, llm_metrics, llm_skip_reason = evaluate_rule_plus_llm()

    effective_llm_metrics = llm_metrics
    if llm_skip_reason and llm_metrics["llm_fallback_hits"] == 0:
        effective_llm_metrics = None
        llm_results = None

    write_compare_outputs(
        rule_metrics=rule_metrics,
        llm_metrics=effective_llm_metrics,
        llm_skip_reason=llm_skip_reason,
        llm_results=llm_results,
    )

    print(
        json.dumps(
            {
                "rule_only": rule_metrics,
                "rule_plus_llm": effective_llm_metrics,
                "llm_skip_reason": llm_skip_reason,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
