"""轨迹评估测试集生成器（仿 LangSmith 复杂 Agent 评估：trajectory 维度）。

轨迹评估关注 agent 的**决策路径**是否正确，而非最终文本是否完美。它与
``eval/answer`` 互补：answer 评估「说得好不好」，trajectory 评估「走得对不对」。

本生成器**复用** ``eval/answer/gen_cases.py`` 的同一 1000 条样本（相同 seed、
相同消息分布），在其上追加轨迹金标（trajectory ground truth）：

    {
      "id": "ans_0001",
      "category": "order_query",
      "inputs":  {"message": "...", "session_id": "ans-sess-0001"},
      "outputs": {
        ...（answer 评估原有字段）...,
        # ---- 新增轨迹金标 ----
        "expected_node_path":        # 期望执行的节点序列
          ["input_normalizer","intent_router","state_tracker","policy_layer",
           "agent_node","response_generator","context_compressor"],
        "expected_reply_source_node":"response_generator",  # 产出最终回复的节点
        "expected_order_id": "A1001",   # 消息中应被抽取的订单号（无则 null）
        "expected_missing_slots": [],   # 期望的缺失槽位
        "expected_needs_clarification": false
      }
    }

金标推导规则（与 agent 设计对齐，确定性、可解释）：
- ``expected_node_path``：由 expected_action 决定分支（见 _node_path_for_action）。
- ``expected_reply_source_node``：澄清类动作 -> clarification_node；其余 -> response_generator。
- ``expected_order_id``：用 domain.extract_order_id 从消息抽取。
- ``expected_missing_slots``：意图需要 order_id（order_query/logistics/after_sale_refund）
  且消息无订单号 -> ["order_id"]；否则 []。
- ``expected_needs_clarification``：动作属于 ask_intent_clarification/ask_slot_clarification。

用法：
  python3 eval/trajectory/gen_cases.py            # 生成（覆盖）测试集
  python3 eval/trajectory/gen_cases.py --count N  # 目标样本数（默认 1000）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# 复用 answer 评估的同一生成器，保证消息分布完全一致
from eval.answer.gen_cases import generate as generate_answer_cases  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent

# 图节点常量（与 app/business/agent/graph.py 一致）
BASE_PATH = ["input_normalizer", "intent_router", "state_tracker", "policy_layer"]

# 需要订单号的意图（其 schema.required_slots 含 order_id）
ORDER_ID_REQUIRED_MAIN = {"order_query", "logistics", "after_sale_refund"}


def _node_path_for_action(action: str) -> list[str]:
    """由期望动作推导期望节点序列（BASE + 分支 + context_compressor）。"""
    if action == "agent_process":
        return BASE_PATH + ["agent_node", "response_generator", "context_compressor"]
    if action == "handoff_human":
        return BASE_PATH + ["handoff_node", "response_generator", "context_compressor"]
    if action in {"ask_intent_clarification", "ask_slot_clarification"}:
        return BASE_PATH + ["clarification_node", "context_compressor"]
    # answer_directly 及其它
    return BASE_PATH + ["response_generator", "context_compressor"]


def _reply_source_for_action(action: str) -> str:
    if action in {"ask_intent_clarification", "ask_slot_clarification"}:
        return "clarification_node"
    return "response_generator"


def _augment(case: dict) -> dict:
    """在 answer 评估样本上追加轨迹金标字段。"""
    from app.business.tools.domain import extract_order_id

    msg = case["inputs"]["message"]
    out = case["outputs"]
    action = out["expected_action"]
    main = out["expected_main_intent"]

    order_id = extract_order_id(msg)
    needs_clar = action in {"ask_intent_clarification", "ask_slot_clarification"}

    if case["category"] == "clarify_no_id":
        missing = ["order_id"]
    elif main in ORDER_ID_REQUIRED_MAIN and not order_id:
        missing = ["order_id"]
    else:
        missing = []

    out["expected_node_path"] = _node_path_for_action(action)
    out["expected_reply_source_node"] = _reply_source_for_action(action)
    out["expected_order_id"] = order_id
    out["expected_missing_slots"] = missing
    out["expected_needs_clarification"] = needs_clar
    return case


def generate(target: int | None = None) -> list[dict]:
    cases = generate_answer_cases(target=target)
    for c in cases:
        _augment(c)
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="生成轨迹评估测试集")
    parser.add_argument("--count", type=int, default=1000, help="目标样本数（默认 1000）")
    args = parser.parse_args()

    cases = generate(target=args.count)

    out_path = EVAL_DIR / "trajectory_eval_cases.json"
    backup = out_path.with_suffix(".json.bak")
    if out_path.exists():
        out_path.replace(backup)
        print(f"[BACKUP] 旧测试集已备份到 {backup.name}")

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

    from collections import Counter
    cat_counter = Counter(c["category"] for c in cases)
    path_counter = Counter(tuple(c["outputs"]["expected_node_path"]) for c in cases)
    print(f"[OK] 已生成 {len(cases)} 条样本（含轨迹金标）-> {out_path.name}")
    print("  按类别：")
    for k, v in cat_counter.most_common():
        print(f"    - {k}: {v}")
    print("  按期望节点路径：")
    for k, v in path_counter.most_common():
        print(f"    - {v:4d}  {list(k)}")


if __name__ == "__main__":
    main()
