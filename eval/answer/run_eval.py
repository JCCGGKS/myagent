"""最终回复评估运行器（仿 LangSmith 复杂 Agent 评估）。

把 ``answer_eval_cases.json`` 当作评估数据集，构建完整 ``CustomerServiceAgent``
作为 **target**（即 LangSmith 的 target/prediction 函数），逐条跑出最终回复，
再用一组 **evaluator** 打分：

  - ``final_answer_correct``  : LLM-as-judge，比对「理想回复 + 必含事实 + 评分要点」
                                与 agent 实际回复，给出 is_correct / score / reasoning。
  - ``key_facts_present``     : 规则评估，检查 reply 是否包含全部 must_contain 事实点。
  - ``intent_correct``        : 规则评估，预测意图 == 期望意图。
  - ``action_correct``        : 规则评估，预测动作 == 期望动作（agent_process 时再校验工具 kind）。

输出：``answer_eval_results.json``（逐条明细 + 指标）与 ``answer_eval_report.md``。

与 LangSmith 的对应关系（本仓库不依赖 langsmith 包，纯本地复刻其方法论）：
  - dataset example 的 ``inputs`` / ``outputs(reference)``  -> 见 gen_cases.py
  - target       -> :func:`run_target`（agent.chat 跑全图）
  - evaluators   -> 下方 eval_* 函数（签名 ``(pred, ref, case) -> 分数``）
  - experiment   -> :func:`run_eval` 收集全部 prediction + score，落盘报告

用法：
  python3 eval/answer/run_eval.py                   # 全量（1000 条，含 LLM 裁判）
  python3 eval/answer/run_eval.py --limit 20        # 小样本快速验证
  python3 eval/answer/run_eval.py --no-llm-judge    # 仅规则评估（不调 LLM 裁判，最省）
  python3 eval/answer/run_eval.py --max-concurrency 8
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

EVAL_DIR = ROOT / "eval" / "answer"
CASES_PATH = EVAL_DIR / "answer_eval_cases.json"
RESULTS_PATH = EVAL_DIR / "answer_eval_results.json"
REPORT_PATH = EVAL_DIR / "answer_eval_report.md"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===== Agent / Judge 构建（镜像 app/api/chat.py）=====
def build_agent():
    """构建完整 CustomerServiceAgent（与 API 层一致），供评估作为 target。"""
    from app.business import (
        CustomerServiceAgent,
        HandoffService,
        LLMIntentFallbackService,
        LogisticsService,
        OrderService,
        RefundService,
    )
    from app.business.dialog import SessionService, get_session_service
    from app.config import load_llm_config
    from app.pkgs.llm import build_async_openai_client
    from app.schema import ChatRequest

    session_service: SessionService = get_session_service()
    llm_config = load_llm_config()
    llm_client = build_async_openai_client(llm_config)
    agent = CustomerServiceAgent(
        store=session_service,
        order_service=OrderService(),
        logistics_service=LogisticsService(),
        handoff_service=HandoffService(),
        refund_service=RefundService(),
        llm_fallback_service=LLMIntentFallbackService(llm_config),
        llm_client=llm_client,
        llm_model=llm_config.model if llm_client is not None else None,
        llm_config=llm_config,
    )
    return agent, session_service, llm_client, llm_config.model, llm_config


# ===== Target：跑全图得到预测 =====
async def run_target(case: dict, agent, session_service) -> dict:
    """LangSmith 的 target：把一条样本 inputs 喂给 agent，返回预测 dict。"""
    from app.schema import ChatRequest, ConversationState

    msg = case["inputs"]["message"]
    sid = case["inputs"]["session_id"]
    prev_sub = case["inputs"].get("previous_sub_intent")

    # 多轮跟进：先把上一轮子意图写进 checkpointer，使 slot_followup 路由生效
    if prev_sub:
        prior = ConversationState(session_id=sid, user_id=0, channel="web")
        prior.current_sub_intent = prev_sub
        prior.current_main_intent = prev_sub.split(".", 1)[0]
        agent.graph.update_state(
            {"configurable": {"thread_id": sid}}, {"state": prior}
        )

    await session_service.ensure_session(sid, 0, "web")
    req = ChatRequest(session_id=sid, message=msg, channel="web")
    resp = await agent.chat(req, user_id=0)

    state = await _get_final_state(agent, sid)
    return {
        "reply": resp.reply,
        "main_intent": state.current_main_intent if state else None,
        "sub_intent": state.current_sub_intent if state else None,
        "action": state.current_action if state else None,
        "tool_kind": state.tool_result.kind if (state and state.tool_result) else None,
        "session_state": resp.session_state,
    }


async def _get_final_state(agent, sid):
    """从 checkpointer 取回最终状态（含 current_action / tool_result）。"""
    config = {"configurable": {"thread_id": sid}}
    if agent.checkpointer is not None and hasattr(agent.checkpointer, "aget_tuple"):
        snap = await agent.graph.aget_state(config)
    else:
        snap = agent.graph.get_state(config)
    if snap and getattr(snap, "values", None):
        return snap.values.get("state")
    return None


# ===== Evaluators =====
def eval_key_facts(pred: dict, ref: dict) -> tuple[bool, list[str]]:
    """规则评估：reply 是否包含全部必含事实点。"""
    reply = pred.get("reply") or ""
    miss = [mc for mc in ref.get("must_contain", []) if mc not in reply]
    return (len(miss) == 0), miss


def eval_intent(pred: dict, ref: dict) -> bool:
    """规则评估：预测主/子意图 == 期望。"""
    return (
        pred.get("main_intent") == ref["expected_main_intent"]
        and pred.get("sub_intent") == ref["expected_sub_intent"]
    )


def eval_action(pred: dict, ref: dict) -> bool:
    """规则评估：预测动作 == 期望；agent_process 时再校验工具 kind。"""
    if pred.get("action") != ref["expected_action"]:
        return False
    tool = ref.get("expected_tool")
    if tool:
        return pred.get("tool_kind") == tool
    return True


def _extract_json(text: str) -> dict:
    """从 LLM 输出中尽量稳健地抽取 JSON 对象。"""
    text = text.strip()
    # 去 ```json 围栏
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        # 取第一个 { 到最后一个 } 之间的内容
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1 and e > s:
            text = text[s : e + 1]
    try:
        return json.loads(text)
    except Exception:
        return {}


async def eval_final_answer_judge(
    pred: dict, ref: dict, case: dict,
    judge_client, judge_model: str, gen_kwargs: dict,
) -> tuple[bool | None, float | None, str]:
    """LLM-as-judge：比对理想回复与学生回复，给出 is_correct / score / reasoning。"""
    from app.utils.llm import call_llm_async

    system = (
        "你是一名严格的客服质检员。请判断【待评估回复】是否合格："
        "1) 是否准确回应了用户诉求；2) 是否包含期望的关键信息（必含事实点）；"
        "3) 语气是否专业友好、无编造。只要实质满足即判为正确，不要求与理想回复逐字一致。"
        "只输出一个 JSON 对象，格式："
        '{"reasoning": "简短理由", "is_correct": true/false, "score": 0.0~1.0}。不要输出多余内容。'
    )
    user = (
        f"用户问题：{case['inputs']['message']}\n"
        f"期望意图：{ref['expected_main_intent']}.{ref['expected_sub_intent']}\n"
        f"期望动作：{ref['expected_action']}\n"
        f"理想回复参考：{ref['reference_reply']}\n"
        f"必含事实点：{ref['must_contain']}\n"
        f"评分要点：{ref['rubric']}\n\n"
        f"待评估回复：{pred['reply']}"
    )
    try:
        resp = await call_llm_async(
            judge_client, judge_model,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            generation_kwargs=gen_kwargs,
        )
        data = _extract_json(resp.get("content", ""))
        is_correct = data.get("is_correct")
        score = data.get("score")
        reasoning = str(data.get("reasoning", ""))
        if isinstance(is_correct, str):
            is_correct = is_correct.strip().lower() in ("true", "1", "是")
        if not isinstance(score, (int, float)):
            score = 1.0 if is_correct else 0.0
        return bool(is_correct), float(score), reasoning
    except Exception as exc:  # noqa: BLE001
        return None, None, f"judge error: {exc}"


# ===== 主评估流程 =====
async def run_eval(
    cases: list[dict], agent, session_service,
    use_judge: bool, judge_client, judge_model: str, gen_kwargs: dict,
    max_concurrency: int,
) -> list[dict]:
    sem = asyncio.Semaphore(max_concurrency)

    async def _one(case: dict) -> dict:
        async with sem:
            import time
            t0 = time.perf_counter()
            pred = await run_target(case, agent, session_service)
            latency = time.perf_counter() - t0
        ref = case["outputs"]
        kf_pass, kf_miss = eval_key_facts(pred, ref)
        intent_pass = eval_intent(pred, ref)
        action_pass = eval_action(pred, ref)
        judge_correct = judge_score = None
        judge_reasoning = ""
        if use_judge and judge_client is not None:
            judge_correct, judge_score, judge_reasoning = await eval_final_answer_judge(
                pred, ref, case, judge_client, judge_model, gen_kwargs
            )
        return {
            "id": case["id"],
            "category": case["category"],
            "message": case["inputs"]["message"],
            **ref,
            "pred_reply": pred["reply"],
            "pred_main_intent": pred["main_intent"],
            "pred_sub_intent": pred["sub_intent"],
            "pred_action": pred["action"],
            "pred_tool_kind": pred["tool_kind"],
            "key_facts_pass": kf_pass,
            "key_facts_miss": kf_miss,
            "intent_pass": intent_pass,
            "action_pass": action_pass,
            "judge_correct": judge_correct,
            "judge_score": judge_score,
            "judge_reasoning": judge_reasoning,
            "latency_s": round(latency, 3),
        }

    return await asyncio.gather(*(_one(c) for c in cases))


def _aggregate(results: list[dict], use_judge: bool) -> dict:
    total = len(results)
    kf = sum(1 for r in results if r["key_facts_pass"])
    it = sum(1 for r in results if r["intent_pass"])
    ac = sum(1 for r in results if r["action_pass"])
    jc = [r for r in results if r["judge_correct"] is not None]
    jc_pass = sum(1 for r in jc if r["judge_correct"])
    jc_score_sum = sum(r["judge_score"] for r in jc if r["judge_score"] is not None)

    # 响应时间统计（每条样本 agent 产出最终回复的耗时，不含 LLM 裁判）
    lats = [r["latency_s"] for r in results if r.get("latency_s") is not None]
    lat_min = min(lats) if lats else 0.0
    lat_max = max(lats) if lats else 0.0
    lat_avg = (sum(lats) / len(lats)) if lats else 0.0
    lat_p50 = (sorted(lats)[len(lats) // 2] if lats else 0.0)

    def pct(n: int) -> float:
        return round(n / total, 4) if total else 0.0

    # 按类别拆解
    by_cat: dict[str, dict[str, int]] = {}
    for r in results:
        b = by_cat.setdefault(r["category"], {"total": 0, "kf": 0, "it": 0, "ac": 0, "jc": 0, "jc_n": 0, "lat": []})
        b["total"] += 1
        if r["key_facts_pass"]:
            b["kf"] += 1
        if r["intent_pass"]:
            b["it"] += 1
        if r["action_pass"]:
            b["ac"] += 1
        if r["judge_correct"] is not None:
            b["jc_n"] += 1
            if r["judge_correct"]:
                b["jc"] += 1
        if r.get("latency_s") is not None:
            b["lat"].append(r["latency_s"])

    per_cat = {}
    for cat, b in sorted(by_cat.items()):
        per_cat[cat] = {
            "total": b["total"],
            "key_facts": pct(b["kf"]),
            "intent": pct(b["it"]),
            "action": pct(b["ac"]),
            "judge": pct(b["jc"]) if b["jc_n"] else None,
            "avg_latency_s": round(sum(b["lat"]) / len(b["lat"]), 3) if b["lat"] else 0.0,
        }

    return {
        "total": total,
        "key_facts_accuracy": pct(kf),
        "intent_accuracy": pct(it),
        "action_accuracy": pct(ac),
        "judge_accuracy": round(jc_pass / len(jc), 4) if jc else None,
        "judge_avg_score": round(jc_score_sum / len(jc), 4) if jc else None,
        "latency": {
            "min_s": round(lat_min, 3),
            "max_s": round(lat_max, 3),
            "avg_s": round(lat_avg, 3),
            "p50_s": round(lat_p50, 3),
        },
        "per_category": per_cat,
        "failed_cases": [r for r in results if not (r["key_facts_pass"] and r["intent_pass"] and r["action_pass"])],
    }


def write_report(metrics: dict, use_judge: bool) -> None:
    lines = [
        "# 最终回复评估报告",
        "",
        "## 总体结果",
        f"- 样本总数：{metrics['total']}",
        f"- 关键事实命中率（key_facts）：{metrics['key_facts_accuracy']:.2%}",
        f"- 意图准确率（intent）：{metrics['intent_accuracy']:.2%}",
        f"- 动作/轨迹准确率（action）：{metrics['action_accuracy']:.2%}",
    ]
    if use_judge and metrics.get("judge_accuracy") is not None:
        lines += [
            f"- LLM 裁判通过率（final_answer_correct）：{metrics['judge_accuracy']:.2%}",
            f"- LLM 裁判平均得分：{metrics['judge_avg_score']:.3f}",
        ]
    lat = metrics.get("latency") or {}
    if lat:
        lines += [
            "",
            "## 响应时间（单条样本 agent 产出最终回复耗时，不含 LLM 裁判）",
            f"- 最短：{lat['min_s']:.3f}s",
            f"- 最长：{lat['max_s']:.3f}s",
            f"- 平均：{lat['avg_s']:.3f}s",
            f"- P50：{lat['p50_s']:.3f}s",
        ]
    lines += ["", "## 按类别", "",
              "| 类别 | 样本数 | 关键事实 | 意图 | 动作 |" +
              (" LLM裁判 |" if (use_judge and metrics.get('judge_accuracy') is not None) else "") +
              " 平均耗时(s) |",
              "|---|---|---|---|---|" +
              ("---|" if (use_judge and metrics.get('judge_accuracy') is not None) else "") +
              "---|"]
    for cat, v in metrics["per_category"].items():
        row = (f"| {cat} | {v['total']} | {v['key_facts']:.2%} "
               f"| {v['intent']:.2%} | {v['action']:.2%} |")
        if use_judge and metrics.get("judge_accuracy") is not None and v["judge"] is not None:
            row += f" {v['judge']:.2%} |"
        elif use_judge and metrics.get("judge_accuracy") is not None:
            row += " - |"
        else:
            row += " "
        row += f" {v['avg_latency_s']:.3f} |"
        lines.append(row)

    failed = metrics["failed_cases"][:60]
    lines += ["", f"## 未完全达标样本（前 {len(failed)} 条）", ""]
    for r in failed:
        lines.append(
            f"- `{r['id']}` [{r['category']}] `{r['message']}`  "
            f"期望 `{r['expected_main_intent']}/{r['expected_sub_intent']}` 动作 {r['expected_action']}；"
            f"实际 `{r['pred_main_intent']}/{r['pred_sub_intent']}` 动作 {r['pred_action']} 工具 {r['pred_tool_kind']}  "
            f"事实{r['key_facts_pass']}/意图{r['intent_pass']}/动作{r['action_pass']}"
            + (f" 裁判{r['judge_correct']}" if r['judge_correct'] is not None else "")
        )
        if not r["key_facts_pass"]:
            lines.append(f"    - 缺失事实点：{r['key_facts_miss']}")
        if r.get("judge_reasoning"):
            lines.append(f"    - 裁判理由：{r['judge_reasoning']}")

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="最终回复评估")
    parser.add_argument("--limit", type=int, default=0, help="仅跑前 N 条（默认 0=全量）")
    parser.add_argument("--no-llm-judge", action="store_true", help="跳过 LLM 裁判，仅规则评估")
    parser.add_argument("--max-concurrency", type=int, default=5, help="并发数（默认 5）")
    parser.add_argument("--cases", type=str, default=str(CASES_PATH), help="数据集路径")
    args = parser.parse_args()

    cases = load_json(Path(args.cases))
    if args.limit:
        cases = cases[: args.limit]

    agent, session_service, judge_client, judge_model, llm_config = build_agent()
    # 触发 checkpointer 初始化（首次异步请求前），multiturn 才能 update_state
    asyncio.run(agent._ensure_checkpointer())

    use_judge = (not args.no_llm_judge) and judge_client is not None
    # 裁判用确定性更强的生成参数（temperature=0，关闭思维链）
    gen_kwargs = dict(llm_config.generation_kwargs())
    gen_kwargs["temperature"] = 0
    gen_kwargs.setdefault("extra_body", {"enable_thinking": False})

    print(f"=== 最终回复评估：{len(cases)} 条，LLM裁判={'开' if use_judge else '关'} ===")
    results = asyncio.run(run_eval(
        cases, agent, session_service, use_judge,
        judge_client, judge_model, gen_kwargs, args.max_concurrency,
    ))

    metrics = _aggregate(results, use_judge)
    save_json(RESULTS_PATH, {"metrics": metrics, "results": results})
    write_report(metrics, use_judge)

    print(f"  关键事实命中率：{metrics['key_facts_accuracy']:.2%}")
    print(f"  意图准确率：{metrics['intent_accuracy']:.2%}")
    print(f"  动作/轨迹准确率：{metrics['action_accuracy']:.2%}")
    if metrics.get("judge_accuracy") is not None:
        print(f"  LLM裁判通过率：{metrics['judge_accuracy']:.2%}（均分 {metrics['judge_avg_score']:.3f}）")
    print(f"[OK] 结果 -> {RESULTS_PATH.name}，报告 -> {REPORT_PATH.name}")


if __name__ == "__main__":
    main()
