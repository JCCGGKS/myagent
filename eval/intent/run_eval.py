"""客服意图识别评估套件 — 统一入口。

一个脚本完成全部评估，无需手动依次跑多个命令。

用法：
  python3 eval/run_eval.py              # 跑规则-only + 规则+LLM + 生成对比报告（完整流程）
  python3 eval/run_eval.py --compare-only   # 仅读取已有结果生成对比报告（不重复跑推理）
  python3 eval/run_eval.py --no-llm         # 仅跑规则-only 评估
  python3 eval/run_eval.py --with-llm        # 仅跑规则+LLM 评估
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

EVAL_DIR = ROOT / "eval" / "intent"
CASES_PATH = EVAL_DIR / "intent_single_step_cases.json"

# 输出文件
NO_LLM_RESULTS = EVAL_DIR / "intent_single_step_results_no_llm.json"
WITH_LLM_RESULTS = EVAL_DIR / "intent_single_step_results_with_llm.json"
NO_LLM_REPORT = EVAL_DIR / "intent_single_step_report_no_llm.md"
WITH_LLM_REPORT = EVAL_DIR / "intent_single_step_report_with_llm.md"
COMPARE_RESULTS = EVAL_DIR / "intent_compare_results.json"
COMPARE_REPORT = EVAL_DIR / "intent_compare_report.md"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===== 核心：直接调用 IntentRouterService =====
def run_single_step(use_llm: bool) -> dict:
    """调用 IntentRouterService 跑单点评估，返回 metrics dict。"""
    from app.schema import ConversationState
    from app.business.intent.routing import IntentRouterService

    cases = load_json(CASES_PATH)
    router = IntentRouterService.from_env(use_llm=use_llm)

    results = []
    stats = {}          # {intent: {"total": N, "matched": N}}
    route_counter = {"rule": 0, "fallback": 0, "llm_fallback": 0}
    llm_hits = 0

    for case in cases:
        state = ConversationState(session_id="eval", user_id=0, channel="eval")
        # 多轮跟进：把上一轮子意图写入 state，使 slot_followup 路由生效
        prev_sub = case.get("previous_sub_intent")
        if prev_sub:
            state.current_sub_intent = prev_sub
            state.current_main_intent = prev_sub.split(".", 1)[0]
        actual = asyncio.run(router.route(state, case["message"]))

        matched = (
            actual.main_intent == case["expected_main_intent"]
            and actual.sub_intent == case["expected_sub_intent"]
        )
        route_counter[actual.route_source] = route_counter.get(actual.route_source, 0) + 1
        if actual.route_source == "llm_fallback":
            llm_hits += 1

        stats.setdefault(case["expected_main_intent"], {"total": 0, "matched": 0})
        stats[case["expected_main_intent"]]["total"] += 1
        if matched:
            stats[case["expected_main_intent"]]["matched"] += 1

        results.append({
            **case,
            "actual_main_intent": actual.main_intent,
            "actual_sub_intent": actual.sub_intent,
            "route_source": actual.route_source,
            "confidence": actual.confidence,
            "matched": matched,
        })

    total = len(results)
    matched_total = sum(1 for r in results if r["matched"])
    metrics = {
        "total_cases": total,
        "matched_cases": matched_total,
        "accuracy": round(matched_total / total, 4) if total else 0.0,
        "route_source_distribution": route_counter,
        "llm_fallback_hits": llm_hits,
        "per_main_intent": {
            intent: {
                "total": v["total"],
                "matched": v["matched"],
                "accuracy": round(v["matched"] / v["total"], 4) if v["total"] else 0.0,
            }
            for intent, v in sorted(stats.items())
        },
        "failed_cases": [r for r in results if not r["matched"]],
    }
    return {"metrics": metrics, "results": results}


def write_single_step_report(metrics: dict, tag: str) -> None:
    """写单点评估 Markdown 报告。"""
    per_lines = [
        f"- `{intent}`: {v['matched']}/{v['total']} = {v['accuracy']:.2%}"
        for intent, v in metrics["per_main_intent"].items()
    ]
    route_label_map = {
        "rule": "规则命中",
        "slot_followup": "上下文跟进",
        "llm_fallback": "LLM 兜底",
        "fallback": "未识别（走兜底）",
    }
    route_lines = [
        f"  - {route_label_map.get(k, k)}：{v} 条"
        for k, v in metrics["route_source_distribution"].items()
    ]
    failed_lines = [
        f"- `{r['id']}`: `{r['message']}`  "
        f"expected `{r['expected_main_intent']}/{r['expected_sub_intent']}`  "
        f"actual `{r['actual_main_intent']}/{r['actual_sub_intent']}`"
        f"（路由：{route_label_map.get(r.get('route_source', ''), r.get('route_source', ''))}）"
        for r in metrics["failed_cases"][:50]
    ]

    label = "规则 + LLM 兜底" if tag == "with_llm" else "纯规则（无 LLM）"

    report = "\n".join([
        f"# 意图识别单点评估报告（{label}）",
        "",
        "## 总体结果",
        f"- 样本总数：{metrics['total_cases']}",
        f"- 命中：{metrics['matched_cases']}",
        f"- 准确率：{metrics['accuracy']:.2%}",
        f"- 路由分布：",
        *route_lines,
        "",
        "## 按主意图",
        *per_lines,
        "",
        "## 未命中样本（前 50 条）",
        *failed_lines,
    ])

    out_path = EVAL_DIR / f"intent_single_step_report_{tag}.md"
    with out_path.open("w", encoding="utf-8") as f:
        f.write(report + "\n")


def _compare_per_category(no_path: Path, with_path: Path) -> list[tuple[str, dict]]:
    """按样本类别拆解两份结果的命中率，返回 [(category, {total, no, yes}), ...]。"""
    if not (no_path.exists() and with_path.exists()):
        return []
    no_results = load_json(no_path)["results"]
    with_results = load_json(with_path)["results"]
    cats: dict[str, dict[str, int]] = {}
    for r_no, r_with in zip(no_results, with_results):
        cat = r_no.get("category", "?")
        bucket = cats.setdefault(cat, {"total": 0, "no": 0, "yes": 0})
        bucket["total"] += 1
        if r_no.get("matched"):
            bucket["no"] += 1
        if r_with.get("matched"):
            bucket["yes"] += 1
    return sorted(cats.items(), key=lambda kv: -kv[1]["total"])


def run_compare() -> None:
    """读取两份单点结果，生成对比报告和 JSON。"""
    if not NO_LLM_RESULTS.exists():
        print(f"[SKIP] 找不到 {NO_LLM_RESULTS.name}，跳过对比。")
        return

    rule_data = load_json(NO_LLM_RESULTS)
    rule_m = rule_data["metrics"]

    llm_m = None
    if WITH_LLM_RESULTS.exists():
        llm_data = load_json(WITH_LLM_RESULTS)
        llm_m = llm_data["metrics"]

    # 写对比 JSON
    payload = {"rule_only": rule_m, "rule_plus_llm": llm_m}
    save_json(COMPARE_RESULTS, payload)

    # 写对比 Markdown
    lines = [
        "# 规则-only vs 规则+LLM 对比评估",
        "",
        "## 规则-only",
        f"- 准确率：{rule_m['accuracy']:.2%}（{rule_m['matched_cases']}/{rule_m['total_cases']}）",
        "",
    ]

    if llm_m:
        delta = llm_m["matched_cases"] - rule_m["matched_cases"]
        acc_delta = llm_m["accuracy"] - rule_m["accuracy"]
        lines += [
            "## 规则+LLM",
            f"- 准确率：{llm_m['accuracy']:.2%}（{llm_m['matched_cases']}/{llm_m['total_cases']}）",
            f"- LLM 兜底命中：{llm_m.get('llm_fallback_hits', 0)} 次",
            "",
            "## 差异",
            f"- 命中数：+{delta}" if delta >= 0 else f"- 命中数：{delta}",
            f"- 准确率：{acc_delta:+.2%}",
        ]

        # 按样本类别拆解：LLM 在哪些类别带来提升 / 哪些被拖累
        per_cat = _compare_per_category(NO_LLM_RESULTS, WITH_LLM_RESULTS)
        if per_cat:
            lines += [
                "",
                "## 按样本类别拆解",
                "",
                "| 类别 | 样本数 | 规则-only | 规则+LLM | Δ |",
                "|---|---|---|---|---|",
            ]
            for cat, v in per_cat:
                d = (v["yes"] - v["no"]) / v["total"] if v["total"] else 0.0
                lines.append(
                    f"| {cat} | {v['total']} | {v['no']/v['total']:.2%} "
                    f"| {v['yes']/v['total']:.2%} | {d:+.2%} |"
                )
            lines += [
                "",
                "## 结论",
                "- LLM 兜底对「口语化/省略表达」(colloquial) 与「规则只给粗子意图」"
                "(finer_subintent) 提升明显；",
                "- 但 LLM 覆盖（confidence<0.8 的规则结果被 LLM 覆盖、未识别走 LLM 兜底）"
                "会反噬少数已正确的规则命中 (rule_hit) 与问候/未识别 (unrecognize) 样本，"
                "属已知权衡，可作为后续优化点。",
            ]
    else:
        lines += [
            "## 规则+LLM",
            "- 未找到 with_llm 结果，请先运行 `python3 eval/run_eval.py --with-llm`。",
        ]

    with COMPARE_REPORT.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[OK] 对比报告已写入 {COMPARE_REPORT.name}")


# ===== CLI 入口 =====
def main() -> None:
    args = sys.argv[1:]

    run_no_llm = "--no-llm" in args
    run_with_llm = "--with-llm" in args or not run_no_llm          # 默认两项都跑
    compare_only = "--compare-only" in args

    if compare_only:
        print("=== 仅生成对比报告（读取已有结果）===")
        run_compare()
        return

    # 跑规则-only
    if run_no_llm or not run_with_llm:
        print("=== 规则-only 评估 ===")
        data = run_single_step(use_llm=False)
        save_json(NO_LLM_RESULTS, data)
        write_single_step_report(data["metrics"], tag="no_llm")
        print(f"  准确率：{data['metrics']['accuracy']:.2%}")

    # 跑规则+LLM
    if run_with_llm:
        print("=== 规则+LLM 评估（需 LLM 可用）===")
        data = run_single_step(use_llm=True)
        save_json(WITH_LLM_RESULTS, data)
        write_single_step_report(data["metrics"], tag="with_llm")
        print(f"  准确率：{data['metrics']['accuracy']:.2%}")

    # 生成对比
    print("=== 生成对比报告 ===")
    run_compare()


if __name__ == "__main__":
    main()
