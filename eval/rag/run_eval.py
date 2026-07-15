"""RAG 检索评测执行器（白盒检索层）。

读取 `rag_eval_cases.json`，将 `template/knowledge/md/` 全部文档入库到**独立的评测
集合**（不污染生产 `customer_service_knowledge`），然后对每个 query 跑 bm25 / semantic /
hybrid 三种检索策略，计算确定性指标并出报告。

指标（均确定性、零 LLM 调用，对齐 eval_rag.md §4 / §6.3）：
- Recall@k        ：金标事实点（must_contain）在前 k 个召回块中的覆盖率（文档召回率口径）
- context_recall  ：金标文档（expected_doc）是否出现在前 k 个召回块中（文档级召回，0/1）
- context_precision：前 k 个召回块中「相关块」占比（相关 = 命中金标文档 或 含任一事实点）
- MRR             ：首个「命中金标文档」块的排名倒数（无则 0）

依赖：Qdrant 在线 + 配置正确的 qdrant 段；semantic/hybrid 还需顶层 embedding 段
（api_key）。未配 embedding 时自动跳过 semantic/hybrid，仅跑 bm25。

用法：
  python3 eval/rag/run_eval.py                      # 全量，三策略（可行时）
  python3 eval/rag/run_eval.py --strategies bm25   # 仅 BM25（无需 embedding）
  python3 eval/rag/run_eval.py --k 3 --limit 10    # 自定义 k 与样本数
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.business.rag.ingestion import (  # noqa: E402
    KnowledgeIngestionService,
    build_embedding_client,
)
from app.business.rag.retrieval.bm25 import BM25Strategy  # noqa: E402
from app.business.rag.retrieval.semantic import SemanticStrategy  # noqa: E402
from app.business.rag.retrieval.hybrid import HybridStrategy  # noqa: E402
from app.config.rag_config import get_rag_config_service  # noqa: E402
from app.pkgs.vector import get_qdrant_client  # noqa: E402

EVAL_COLLECTION = "rag_eval_knowledge"
KNOWLEDGE_MD_DIR = ROOT / "template" / "knowledge" / "md"


# --------------------------------------------------------------------------- #
# 入库
# --------------------------------------------------------------------------- #
def reset_collection(client) -> None:
    """清空评测集合，避免跨次运行累积重复向量。"""
    real = client._client
    try:
        if real.collection_exists(EVAL_COLLECTION):
            real.delete_collection(EVAL_COLLECTION)
            print(f"[RESET] 已删除旧评测集合 {EVAL_COLLECTION}")
    except Exception as exc:  # noqa: BLE001
        print(f"[RESET] 集合删除跳过：{exc!r}")


def ingest_corpus(client, doc_map: dict[str, str]) -> int:
    """将 md/ 下各文档按 doc_type 入库。

    doc_map: {相对路径(如 md/refund_policy.md): doc_type}
    返回写入块总数。
    """
    embedding_client = build_embedding_client()
    svc = KnowledgeIngestionService(
        qdrant_client=client,
        embedding_client=embedding_client,
        collection_name=EVAL_COLLECTION,
        vector_size=client.vector_size,
    )
    total = 0
    for rel_path, doc_type in doc_map.items():
        fpath = ROOT / "template" / "knowledge" / rel_path
        if not fpath.exists():
            print(f"[WARN] 文档不存在，跳过：{fpath}")
            continue
        doc_id = abs(hash(rel_path)) % (10**9)
        # 先清同文档旧向量，保证幂等
        try:
            client.delete_by_doc_id(doc_id)
        except Exception:
            pass
        n = svc.ingest_markdown_file(
            fpath, doc_type=doc_type, source=fpath.name, doc_id=doc_id
        )
        total += n
        print(f"[INGEST] {rel_path} ({doc_type}) -> {n} 块")
    mode = "dense+bm25" if embedding_client else "bm25-only"
    print(f"[INGEST] 共入库 {total} 块（{mode}）")
    return total


# --------------------------------------------------------------------------- #
# 检索策略构造
# --------------------------------------------------------------------------- #
def build_strategies(client, cfg):
    """按配置构造三种策略；embedding 缺失时 semantic/hybrid 不可用。"""
    emb = build_embedding_client()
    strategies: dict[str, object] = {}
    threshold = cfg.min_score_threshold
    top_k = cfg.top_k

    strategies["bm25"] = BM25Strategy(
        client=client, min_score_threshold=threshold, top_k=top_k
    )

    if emb is None:
        print("[STRATEGY] 未配置 embedding，跳过 semantic / hybrid")
        return strategies

    sem = SemanticStrategy(
        client=client, embedding_client=emb,
        min_score_threshold=threshold, top_k=top_k,
    )
    strategies["semantic"] = sem
    strategies["hybrid"] = HybridStrategy(
        strategies=[
            BM25Strategy(client=client, min_score_threshold=threshold, top_k=top_k),
            sem,
        ],
        min_score_threshold=threshold,
        top_k=top_k,
        rrf_k=cfg.rrf_k,
    )
    return strategies


def dedup(docs):
    """复制 RagRetrieveTool._dedup：按内容去重，保留分数最高者。"""
    best: dict[str, object] = {}
    for d in docs:
        key = (d.content or "").strip()
        if not key:
            continue
        if key not in best or d.score > best[key].score:
            best[key] = d
    return list(best.values())


# --------------------------------------------------------------------------- #
# 指标
# --------------------------------------------------------------------------- #
def _doc_source(doc) -> str:
    meta = doc.metadata or {}
    src = meta.get("source") or (meta.get("metadata") or {}).get("source") or ""
    return src


def compute_metrics(docs, expected_doc: str, must_contain: list[str], k: int) -> dict:
    """对单条 case 的前 k 个召回块计算指标。"""
    top = docs[:k]
    gold_name = Path(expected_doc).name

    # Recall@k：事实点覆盖率
    if must_contain:
        fact_hit = [
            any(fact in (d.content or "") for d in top) for fact in must_contain
        ]
        recall_at_k = sum(fact_hit) / len(must_contain)
    else:
        recall_at_k = 1.0

    # 文档级相关判定：必须同时命中金标文档「且」包含至少一个事实点，
    # 避免「来自金标文档但无关小节」虚高 context_recall / MRR。
    def is_gold(d) -> bool:
        if not (_doc_source(d) and Path(_doc_source(d)).name == gold_name):
            return False
        return any(fact in (d.content or "") for fact in (must_contain or []))

    # context_recall：前 k 中是否出现「金标文档且相关」的块
    context_recall = 1.0 if any(is_gold(d) for d in top) else 0.0

    # context_precision：前 k 中相关块占比
    relevant = sum(1 for d in top if is_gold(d))
    context_precision = (relevant / len(top)) if top else 0.0

    # MRR：首个「金标文档且相关」块的排名倒数
    mrr = 0.0
    for rank, d in enumerate(top, start=1):
        if is_gold(d):
            mrr = 1.0 / rank
            break

    return {
        "recall_at_k": round(recall_at_k, 4),
        "context_recall": context_recall,
        "context_precision": round(context_precision, 4),
        "mrr": round(mrr, 4),
        "retrieved_sources": [
            Path(_doc_source(d)).name for d in top if _doc_source(d)
        ],
    }


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 检索评测执行器")
    parser.add_argument("--cases", default=str(Path(__file__).resolve().parent / "rag_eval_cases.json"))
    parser.add_argument("--knowledge-dir", default=str(KNOWLEDGE_MD_DIR))
    parser.add_argument("--k", type=int, default=None, help="评估截断 k（默认取 rag.top_k）")
    parser.add_argument(
        "--strategies", default="bm25,semantic,hybrid",
        help="启用的策略，逗号分隔；未配 embedding 时 semantic/hybrid 自动跳过",
    )
    parser.add_argument("--limit", type=int, default=None, help="仅评前 N 条 case")
    parser.add_argument("--no-ingest", action="store_true", help="复用已入库数据，不再重新入库")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    if not cases_path.exists():
        print(f"[ERR] 评测集不存在：{cases_path}（请先运行 gen_cases.py）")
        sys.exit(1)
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[: args.limit]

    cfg = get_rag_config_service().get_config()
    k = args.k or cfg.top_k

    # 构建 client（独立评测集合，不污染生产）
    client = get_qdrant_client()
    client.collection_name = EVAL_COLLECTION
    # vector_size 已在 get_qdrant_client 内按配置设定

    # 文档 -> doc_type 映射（从 cases 去重）
    doc_map: dict[str, str] = {}
    for c in cases:
        doc_map[c["expected_doc"]] = c.get("doc_type", "faq")

    if not args.no_ingest:
        reset_collection(client)
        ingest_corpus(client, doc_map)
    else:
        print("[INGEST] --no-ingest：复用已有评测集合数据")

    # 构造策略
    all_strategies = build_strategies(client, cfg)
    wanted = [s.strip() for s in args.strategies.split(",") if s.strip()]
    active = {name: s for name, s in all_strategies.items() if name in wanted}
    if not active:
        print("[ERR] 没有可用的检索策略（检查 embedding 配置或 --strategies）")
        sys.exit(1)
    print(f"[EVAL] 策略={list(active)} k={k} cases={len(cases)}")

    # 跑评测
    per_strategy: dict[str, dict] = {}
    t0 = time.time()
    for name, strat in active.items():
        print(f"\n=== 策略：{name} ===")
        case_results = []
        agg = defaultdict(list)
        for c in cases:
            try:
                docs = strat.retrieve(c["query"], user_id=None)
            except Exception as exc:  # noqa: BLE001
                print(f"  [ERR] {c['id']} {c['query']!r}: {exc!r}")
                continue
            docs = dedup(docs)
            m = compute_metrics(docs, c["expected_doc"], c.get("must_contain", []), k)
            m["id"] = c["id"]
            m["query"] = c["query"]
            m["expected_doc"] = c["expected_doc"]
            case_results.append(m)
            for key in ("recall_at_k", "context_recall", "context_precision", "mrr"):
                agg[key].append(m[key])

        # 按 doc_type 聚合，便于看哪类文档弱
        by_type: dict[str, defaultdict] = defaultdict(lambda: defaultdict(list))
        for c, m in zip(cases, case_results):
            dt = c.get("doc_type", "faq")
            by_type[dt]["n"].append(1)
            for key in ("recall_at_k", "context_recall", "context_precision", "mrr"):
                by_type[dt][key].append(m[key])

        summary = {
            key: round(sum(v) / len(v), 4) if v else 0.0
            for key, v in agg.items()
        }
        summary["n"] = len(case_results)
        summary["by_doc_type"] = {
            t: {key: round(sum(v) / len(v), 4) if v else 0.0 for key, v in metric.items()}
            for t, metric in by_type.items()
        }
        # 修正 by_doc_type 中 n 为计数（上面 dict 里 n 是 [1,1,...]，需取长度）
        for t, metric in summary["by_doc_type"].items():
            metric["n"] = len(by_type[t].get("n", []))
        per_strategy[name] = {"summary": summary, "cases": case_results}
        print(f"  Recall@{k}={summary['recall_at_k']}  "
              f"ctx_recall={summary['context_recall']}  "
              f"ctx_precision={summary['context_precision']}  "
              f"MRR={summary['mrr']}  (n={summary['n']})")

    elapsed = time.time() - t0

    # 输出
    out_dir = Path(__file__).resolve().parent
    results = {
        "config": {
            "k": k,
            "retrieval_strategy": cfg.retrieval_strategy,
            "min_score_threshold": cfg.min_score_threshold,
            "rrf_k": cfg.rrf_k,
            "collection": EVAL_COLLECTION,
            "elapsed_sec": round(elapsed, 2),
        },
        "strategies": per_strategy,
    }
    res_path = out_dir / "rag_eval_results.json"
    res_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] 结果 -> {res_path}")

    _write_report(out_dir / "rag_eval_report.md", results, k)


def _write_report(path: Path, results: dict, k: int) -> None:
    cfg = results["config"]
    lines = [
        "# RAG 检索评测报告",
        "",
        f"> 生成时间无关；k={k}，集合 `{cfg['collection']}`，"
        f"耗时 {cfg['elapsed_sec']}s，阈值={cfg['min_score_threshold']}，rrf_k={cfg['rrf_k']}",
        "",
        "## 策略总览",
        "",
        "| 策略 | n | Recall@k | context_recall | context_precision | MRR |",
        "|---|---|---|---|---|---|",
    ]
    for name, blk in results["strategies"].items():
        s = blk["summary"]
        lines.append(
            f"| {name} | {s['n']} | {s['recall_at_k']} | {s['context_recall']} | "
            f"{s['context_precision']} | {s['mrr']} |"
        )
    lines += ["", "## 指标说明", ""]
    lines += [
        "- **Recall@k**：金标事实点（must_contain）在前 k 个召回块中的覆盖率。",
        "- **context_recall**：金标文档（expected_doc）是否出现在前 k 个召回块（0/1 均值）。",
        "- **context_precision**：前 k 个召回块中相关块占比（命中金标文档或含事实点）。",
        "- **MRR**：首个命中金标文档块的排名倒数。",
        "",
        "## 分 doc_type 明细（Recall@k）",
        "",
        "| 策略 | doc_type | n | Recall@k | context_recall | MRR |",
        "|---|---|---|---|---|---|",
    ]
    for name, blk in results["strategies"].items():
        s = blk["summary"]
        by_type = s.get("by_doc_type", {})
        for dt, m in by_type.items():
            lines.append(
                f"| {name} | {dt} | {m.get('n', '-')} | {m.get('recall_at_k', 0)} | "
                f"{m.get('context_recall', 0)} | {m.get('mrr', 0)} |"
            )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] 报告 -> {path}")


if __name__ == "__main__":
    main()
