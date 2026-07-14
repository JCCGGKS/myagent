"""轨迹评估运行器（仿 LangSmith 复杂 Agent 评估：trajectory 维度）。

把 ``trajectory_eval_cases.json`` 当作数据集，构建完整 ``CustomerServiceAgent``
作为 **target**，但不同于 answer 评估（关心最终文本），本评估用 ``graph.astream``
捕获 agent 的**完整决策轨迹**：

  - ``node_order``       : 节点实际执行顺序（input_normalizer → … → END）
  - ``intent``           : intent_router 节点产出的主/子意图
  - ``slots / missing``  : state_tracker 之后的槽位与缺失槽位
  - ``action``           : policy_layer 的决策动作 + agent_node 调用的工具 kind
  - ``reply_source_node``: 最终回复由哪个节点产出（clarification_node / response_generator）

evaluators（全部规则判定，确定性、可复现，不依赖 LLM 裁判）：
  - ``route_correct``          : 实际节点序列 == 期望节点序列（含分支与 context_compressor）
  - ``intent_correct``         : 预测主/子意图 == 期望
  - ``action_correct``         : 预测动作 == 期望；agent_process 时再校验工具 kind
  - ``slot_extraction_correct``: 消息含订单号时，state.slots 正确抽出该 order_id
  - ``missing_slot_correct``   : 预测缺失槽位 == 期望缺失槽位
  - ``clarification_correct``  : needs_clarification 与期望一致；澄清类还需 reply 追问订单号
  - ``trajectory_overall``     : 以上六项全过 = 端到端走对路径

输出：``trajectory_eval_results.json``（逐条明细 + 指标）与 ``trajectory_eval_report.md``。

与 LangSmith 对应：
  - dataset example 的 inputs/outputs(reference) -> 见 gen_cases.py
  - target       -> :func:`run_target`（graph.astream 捕获轨迹）
  - evaluators   -> 下方 eval_* 函数
  - experiment   -> :func:`run_eval` 收集 prediction + score，落盘报告

用法：
  python3 eval/trajectory/run_eval.py                # 全量（1000 条，规则评估）
  python3 eval/trajectory/run_eval.py --limit 20     # 小样本快速验证
  python3 eval/trajectory/run_eval.py --max-concurrency 8
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

EVAL_DIR = ROOT / "eval" / "trajectory"
CASES_PATH = EVAL_DIR / "trajectory_eval_cases.json"
RESULTS_PATH = EVAL_DIR / "trajectory_eval_results.json"
REPORT_PATH = EVAL_DIR / "trajectory_eval_report.md"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===== Agent 构建（镜像 app/api/chat.py）=====
def build_agent():
    from app.business import (
        CustomerServiceAgent,
        HandoffService,
        LLMIntentFallbackService,
        LogisticsService,
        OrderService,
        RefundService,
    )
    from app.business.dialog import get_session_service
    from app.config import load_llm_config
    from app.pkgs.llm import build_async_openai_client
    from app.schema import ChatRequest

    session_service = get_session_service()
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
    return agent, session_service, llm_config


# ===== Target：graph.astream 捕获完整轨迹 =====
async def run_target(case: dict, agent, session_service) -> dict:
    from app.schema import ChatRequest, ConversationState

    msg = case["inputs"]["message"]
    sid = case["inputs"]["session_id"]
    prev_sub = case["inputs"].get("previous_sub_intent")

    await agent._ensure_checkpointer()

    # 多轮跟进：先把上一轮子意图写进 checkpointer
    if prev_sub:
        prior = ConversationState(session_id=sid, user_id=0, channel="web")
        prior.current_sub_intent = prev_sub
        prior.current_main_intent = prev_sub.split(".", 1)[0]
        agent.graph.update_state(
            {"configurable": {"thread_id": sid}}, {"state": prior}
        )

    await session_service.ensure_session(sid, 0, "web")
    request = ChatRequest(session_id=sid, message=msg, channel="web")
    payload = await agent._build_payload(request, 0)

    config = {"configurable": {"thread_id": sid}}
    node_order: list[str] = []
    intent_main = intent_sub = None
    async for chunk in agent.graph.astream(payload, config=config):
        for node_name, node_payload in chunk.items():
            node_order.append(node_name)
            state = node_payload.get("state") if isinstance(node_payload, dict) else node_payload
            if node_name == "intent_router" and state and state.intent_result:
                intent_main = state.intent_result.main_intent
                intent_sub = state.intent_result.sub_intent

    # 终态：从 checkpointer 取回（含 current_action / slots / missing / tool_results / reply）
    final = await _get_final_state(agent, sid)
    action = final.current_action if final else None
    tool_kind = final.tool_results[-1].kind if (final and final.tool_results) else None
    slots = dict(final.slots) if final else {}
    missing = list(final.missing_slots) if final else []
    needs_clar = bool(final.needs_clarification) if final else False
    reply = final.reply if final else ""
    reply_source = "clarification_node" if "clarification_node" in node_order else "response_generator"

    return {
        "node_order": node_order,
        "main_intent": intent_main,
        "sub_intent": intent_sub,
        "action": action,
        "tool_kind": tool_kind,
        "slots": slots,
        "missing_slots": missing,
        "needs_clarification": needs_clar,
        "reply": reply,
        "reply_source_node": reply_source,
    }


async def _get_final_state(agent, sid):
    config = {"configurable": {"thread_id": sid}}
    if agent.checkpointer is not None and hasattr(agent.checkpointer, "aget_tuple"):
        snap = await agent.graph.aget_state(config)
    else:
        snap = agent.graph.get_state(config)
    if snap and getattr(snap, "values", None):
        return snap.values.get("state")
    return None


# ===== Evaluators（规则判定，确定性）=====
def eval_route(pred: dict, ref: dict) -> bool:
    """实际节点序列是否完全等于期望节点序列。"""
    return pred.get("node_order") == list(ref["expected_node_path"])


def eval_intent(pred: dict, ref: dict) -> bool:
    return (
        pred.get("main_intent") == ref["expected_main_intent"]
        and pred.get("sub_intent") == ref["expected_sub_intent"]
    )


def eval_action(pred: dict, ref: dict) -> bool:
    if pred.get("action") != ref["expected_action"]:
        return False
    tool = ref.get("expected_tool")
    if tool:
        return pred.get("tool_kind") == tool
    return True


def eval_slot_extraction(pred: dict, ref: dict) -> bool:
    """消息含订单号时，state.slots 应正确抽出该 order_id。"""
    exp_oid = ref.get("expected_order_id")
    if not exp_oid:
        return True  # 无订单号可抽，跳过（不算错）
    return pred.get("slots", {}).get("order_id") == exp_oid


def eval_missing_slot(pred: dict, ref: dict) -> bool:
    return set(pred.get("missing_slots", [])) == set(ref["expected_missing_slots"])


def eval_clarification(pred: dict, ref: dict) -> bool:
    """needs_clarification 与期望一致；澄清类还需 reply 实际追问订单号。"""
    if bool(pred.get("needs_clarification")) != bool(ref["expected_needs_clarification"]):
        return False
    if ref["expected_needs_clarification"]:
        return "订单号" in (pred.get("reply") or "")
    return True


def eval_overall(*flags: bool) -> bool:
    return all(flags)


# ===== 主评估流程 =====
async def run_eval(cases: list[dict], agent, session_service, max_concurrency: int) -> list[dict]:
    sem = asyncio.Semaphore(max_concurrency)

    async def _one(case: dict) -> dict:
        async with sem:
            t0 = time.perf_counter()
            pred = await run_target(case, agent, session_service)
            latency = time.perf_counter() - t0
        ref = case["outputs"]
        route_pass = eval_route(pred, ref)
        intent_pass = eval_intent(pred, ref)
        action_pass = eval_action(pred, ref)
        slot_pass = eval_slot_extraction(pred, ref)
        missing_pass = eval_missing_slot(pred, ref)
        clar_pass = eval_clarification(pred, ref)
        overall = eval_overall(route_pass, intent_pass, action_pass, slot_pass, missing_pass, clar_pass)
        return {
            "id": case["id"],
            "category": case["category"],
            "message": case["inputs"]["message"],
            **ref,
            "pred_node_order": pred["node_order"],
            "pred_main_intent": pred["main_intent"],
            "pred_sub_intent": pred["sub_intent"],
            "pred_action": pred["action"],
            "pred_tool_kind": pred["tool_kind"],
            "pred_slots": pred["slots"],
            "pred_missing_slots": pred["missing_slots"],
            "pred_needs_clarification": pred["needs_clarification"],
            "pred_reply_source_node": pred["reply_source_node"],
            "pred_reply": pred["reply"],
            "route_pass": route_pass,
            "intent_pass": intent_pass,
            "action_pass": action_pass,
            "slot_extraction_pass": slot_pass,
            "missing_slot_pass": missing_pass,
            "clarification_pass": clar_pass,
            "trajectory_overall": overall,
            "latency_s": round(latency, 3),
        }

    return await asyncio.gather(*(_one(c) for c in cases))


def _aggregate(results: list[dict]) -> dict:
    total = len(results)

    def cnt(key: str) -> int:
        return sum(1 for r in results if r[key])

    route = cnt("route_pass")
    it = cnt("intent_pass")
    ac = cnt("action_pass")
    slot = cnt("slot_extraction_pass")
    missing = cnt("missing_slot_pass")
    clar = cnt("clarification_pass")
    overall = cnt("trajectory_overall")

    lats = [r["latency_s"] for r in results if r.get("latency_s") is not None]
    lat_min = min(lats) if lats else 0.0
    lat_max = max(lats) if lats else 0.0
    lat_avg = (sum(lats) / len(lats)) if lats else 0.0
    lat_p50 = sorted(lats)[len(lats) // 2] if lats else 0.0

    def pct(n: int) -> float:
        return round(n / total, 4) if total else 0.0

    # 按类别拆解（含 avg_latency）
    by_cat: dict[str, dict[str, int]] = {}
    for r in results:
        b = by_cat.setdefault(
            r["category"],
            {"total": 0, "route": 0, "it": 0, "ac": 0, "slot": 0, "miss": 0, "clar": 0, "ov": 0, "lat": []},
        )
        b["total"] += 1
        if r["route_pass"]:
            b["route"] += 1
        if r["intent_pass"]:
            b["it"] += 1
        if r["action_pass"]:
            b["ac"] += 1
        if r["slot_extraction_pass"]:
            b["slot"] += 1
        if r["missing_slot_pass"]:
            b["miss"] += 1
        if r["clarification_pass"]:
            b["clar"] += 1
        if r["trajectory_overall"]:
            b["ov"] += 1
        if r.get("latency_s") is not None:
            b["lat"].append(r["latency_s"])

    per_cat = {}

    def cpct(n: int, denom: int) -> float:
        # 按类别内准确率：除以该类别样本数，而非全局 total（修复原 pct 用全局分母的 bug）。
        return round(n / denom, 4) if denom else 0.0

    for cat, b in sorted(by_cat.items()):
        per_cat[cat] = {
            "total": b["total"],
            "route": cpct(b["route"], b["total"]),
            "intent": cpct(b["it"], b["total"]),
            "action": cpct(b["ac"], b["total"]),
            "slot_extraction": cpct(b["slot"], b["total"]),
            "missing_slot": cpct(b["miss"], b["total"]),
            "clarification": cpct(b["clar"], b["total"]),
            "trajectory_overall": cpct(b["ov"], b["total"]),
            "avg_latency_s": round(sum(b["lat"]) / len(b["lat"]), 3) if b["lat"] else 0.0,
        }

    return {
        "total": total,
        "route_accuracy": pct(route),
        "intent_accuracy": pct(it),
        "action_accuracy": pct(ac),
        "slot_extraction_accuracy": pct(slot),
        "missing_slot_accuracy": pct(missing),
        "clarification_accuracy": pct(clar),
        "trajectory_overall_accuracy": pct(overall),
        "latency": {
            "min_s": round(lat_min, 3),
            "max_s": round(lat_max, 3),
            "avg_s": round(lat_avg, 3),
            "p50_s": round(lat_p50, 3),
        },
        "per_category": per_cat,
        "failed_cases": [r for r in results if not r["trajectory_overall"]],
    }


def write_report(metrics: dict) -> None:
    lines = [
        "# 轨迹评估报告",
        "",
        "## 总体结果（路径/决策正确性，规则评估，不依赖 LLM 裁判）",
        f"- 样本总数：{metrics['total']}",
        f"- 节点路径准确率（route）：{metrics['route_accuracy']:.2%}",
        f"- 意图准确率（intent）：{metrics['intent_accuracy']:.2%}",
        f"- 动作/分支准确率（action）：{metrics['action_accuracy']:.2%}",
        f"- 槽位抽取准确率（slot_extraction）：{metrics['slot_extraction_accuracy']:.2%}",
        f"- 缺失槽位准确率（missing_slot）：{metrics['missing_slot_accuracy']:.2%}",
        f"- 澄清行为准确率（clarification）：{metrics['clarification_accuracy']:.2%}",
        f"- **轨迹总准确率（trajectory_overall，六项全过）**：{metrics['trajectory_overall_accuracy']:.2%}",
    ]
    lat = metrics.get("latency") or {}
    if lat:
        lines += [
            "",
            "## 响应时间（单条样本 agent 跑完整图耗时，含工具调用，不含 LLM 裁判）",
            f"- 最短：{lat['min_s']:.3f}s",
            f"- 最长：{lat['max_s']:.3f}s",
            f"- 平均：{lat['avg_s']:.3f}s",
            f"- P50：{lat['p50_s']:.3f}s",
        ]
    lines += ["", "## 按类别", "",
              "| 类别 | 样本数 | 路径 | 意图 | 动作 | 槽位抽取 | 缺失槽位 | 澄清 | 总准确率 | 平均耗时(s) |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for cat, v in metrics["per_category"].items():
        lines.append(
            f"| {cat} | {v['total']} | {v['route']:.2%} | {v['intent']:.2%} | "
            f"{v['action']:.2%} | {v['slot_extraction']:.2%} | {v['missing_slot']:.2%} | "
            f"{v['clarification']:.2%} | {v['trajectory_overall']:.2%} | {v['avg_latency_s']:.3f} |"
        )

    failed = metrics["failed_cases"][:80]
    lines += ["", f"## 轨迹未完全达标样本（前 {len(failed)} 条）", ""]
    for r in failed:
        lines.append(
            f"- `{r['id']}` [{r['category']}] `{r['message']}`  "
            f"期望动作 {r['expected_action']}；实际动作 {r['pred_action']} 工具 {r['pred_tool_kind']} 回复节点 {r['pred_reply_source_node']}"
        )
        lines.append(
            f"    - 期望路径 {r['expected_node_path']}"
        )
        lines.append(
            f"    - 实际路径 {r['pred_node_order']}"
        )
        # 标注未过的维度
        dims = []
        if not r["route_pass"]:
            dims.append("路径")
        if not r["intent_pass"]:
            dims.append("意图")
        if not r["action_pass"]:
            dims.append("动作")
        if not r["slot_extraction_pass"]:
            dims.append("槽位抽取")
        if not r["missing_slot_pass"]:
            dims.append("缺失槽位")
        if not r["clarification_pass"]:
            dims.append("澄清")
        if dims:
            lines.append(f"    - 未过维度：{'/'.join(dims)}")

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="轨迹评估")
    parser.add_argument("--limit", type=int, default=0, help="仅跑前 N 条（默认 0=全量）")
    parser.add_argument("--max-concurrency", type=int, default=5, help="并发数（默认 5）")
    parser.add_argument("--cases", type=str, default=str(CASES_PATH), help="数据集路径")
    args = parser.parse_args()

    cases = load_json(Path(args.cases))
    if args.limit:
        cases = cases[: args.limit]

    agent, session_service, _llm_config = build_agent()
    asyncio.run(agent._ensure_checkpointer())

    print(f"=== 轨迹评估：{len(cases)} 条（规则评估，无 LLM 裁判） ===")
    results = asyncio.run(
        run_eval(cases, agent, session_service, args.max_concurrency)
    )

    metrics = _aggregate(results)
    save_json(RESULTS_PATH, {"metrics": metrics, "results": results})
    write_report(metrics)

    print(f"  节点路径准确率：{metrics['route_accuracy']:.2%}")
    print(f"  意图准确率：{metrics['intent_accuracy']:.2%}")
    print(f"  动作/分支准确率：{metrics['action_accuracy']:.2%}")
    print(f"  槽位抽取准确率：{metrics['slot_extraction_accuracy']:.2%}")
    print(f"  缺失槽位准确率：{metrics['missing_slot_accuracy']:.2%}")
    print(f"  澄清行为准确率：{metrics['clarification_accuracy']:.2%}")
    print(f"  轨迹总准确率：{metrics['trajectory_overall_accuracy']:.2%}")
    print(f"[OK] 结果 -> {RESULTS_PATH.name}，报告 -> {REPORT_PATH.name}")


if __name__ == "__main__":
    main()
