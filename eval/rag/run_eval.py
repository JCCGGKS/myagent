#!/usr/bin/env python3
"""RAG 检索质量评估（BM25 腿，端到端命中本地 Qdrant，无需 embedding / LLM）。

背景与边界
----------
- 当前 ``config/llm_config.local.yml`` 的 ``rag.retrieval_strategy = bm25``，
  且 ``embedding.api_key`` 为空（生产入库会跳过向量化）。真实可用的检索腿
  只有 BM25 稀疏向量。
- BM25 稀疏向量由 ``build_sparse_vector`` 在本地构建（**不需要 embedding API**），
  可直接端到端命中本地 Qdrant（默认 127.0.0.1:6333）。
- 因此本评估只覆盖 BM25 腿，验证 ``template/knowledge`` 下的知识文档经
  分块 + 入库后，能否在 top_k 内召回答案所需的关键事实（``must_contain``）。
- 若后续配置语义 / 混合检索，需先填 ``embedding.api_key``，本脚本可扩展为
  对 semantic / hybrid 策略分别评估（见结尾说明）。

指标
----
recall@k（k=1/3/5）= 在 top-k 召回块中命中的关键事实数 / 关键事实总数。
命中判定：关键事实字符串是否作为子串出现在拼接后的召回块文本中。

用法
----
  python3 eval/rag/run_eval.py                 # 跑默认用例集，打印 + 写报告
  python3 eval/rag/run_eval.py --top-k 5       # 自定义 top_k（默认读 rag 配置）
  python3 eval/rag/run_eval.py --no-ingest     # 跳过入库（复用已存在的 eval 集合）
  python3 eval/rag/run_eval.py --report out.md # 指定报告路径（默认 eval/rag/rag_eval_report.md）
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from qdrant_client.models import Modifier, SparseVectorParams

from app.business.rag.chunking.registry import get_chunking_strategy
from app.business.rag.retrieval.bm25 import BM25Strategy
from app.business.rag.sparse_bm25 import build_sparse_vector
from app.config.rag_config import get_rag_config_service
from app.pkgs.vector import get_qdrant_client
from app.pkgs.vector.qdrant import SPARSE_VECTOR_NAME

# --------------------------------------------------------------------------- #
# 评估集合（eval 专用，避免污染生产 customer_service_knowledge）
# --------------------------------------------------------------------------- #
EVAL_COLLECTION = "eval_kb_bm25"
KNOWLEDGE_DIR = ROOT / "template" / "knowledge"

# 知识文档 → doc_type（仅作元数据，BM25 检索不使用；与生产入库口径一致）
DOC_TYPE_MAP: dict[str, str] = {
    "refund_policy.md": "policy",
    "after_sale.md": "faq",
    "logistics_shipping.md": "faq",
    "order_faq.md": "faq",
    "invoice_rule.md": "faq",
    "membership_faq.md": "faq",
    "product_robot_pro.md": "product",
    "product_kb_pack.md": "product",
}

# 评估用例：每条对齐一个知识文档（category），query 为用户口语化问法，
# must_contain 为答案必须检索到的关键事实（子串匹配，取自真实文档原文）。
CASES: list[dict] = [
    # 退款政策
    {"id": "rag_001", "category": "refund_policy", "query": "七天无理由退货怎么操作",
     "must_contain": ["七天无理由", "原路退回"]},
    {"id": "rag_002", "category": "refund_policy", "query": "退款一般多久能到账",
     "must_contain": ["原路退回", "1-3 个工作日"]},
    {"id": "rag_003", "category": "refund_policy", "query": "哪些情况不支持无理由退款",
     "must_contain": ["不支持无理由退款", "虚拟商品"]},
    {"id": "rag_004", "category": "refund_policy", "query": "退款进度都有哪些状态",
     "must_contain": ["审核中", "已退款"]},
    # 售后 / 退换货
    {"id": "rag_005", "category": "after_sale", "query": "退货退款的流程是什么",
     "must_contain": ["退货退款", "运费由用户承担"]},
    {"id": "rag_006", "category": "after_sale", "query": "智能客服机器人Pro质保多久",
     "must_contain": ["整机一年质保", "主要部件两年"]},
    {"id": "rag_007", "category": "after_sale", "query": "什么情况算质量问题可以退换",
     "must_contain": ["质量问题", "运费由商家承担"]},
    # 物流
    {"id": "rag_008", "category": "logistics_shipping", "query": "订单满多少可以包邮",
     "must_contain": ["包邮", "99 元"]},
    {"id": "rag_009", "category": "logistics_shipping", "query": "偏远地区运费怎么算",
     "must_contain": ["偏远地区", "运费"]},
    {"id": "rag_010", "category": "logistics_shipping", "query": "跨省物流一般几天能到",
     "must_contain": ["跨省", "3-5 天"]},
    # 订单 FAQ
    {"id": "rag_011", "category": "order_faq", "query": "怎么修改收货地址",
     "must_contain": ["修改地址", "已发货"]},
    {"id": "rag_012", "category": "order_faq", "query": "已经发货的订单还能取消吗",
     "must_contain": ["已发货", "取消订单"]},
    # 发票
    {"id": "rag_013", "category": "invoice_rule", "query": "怎么开电子发票",
     "must_contain": ["电子普通发票", "1-3 个工作日"]},
    {"id": "rag_014", "category": "invoice_rule", "query": "开增值税专用发票需要什么信息",
     "must_contain": ["增值税专用发票", "企业税号"]},
    # 会员
    {"id": "rag_015", "category": "membership_faq", "query": "金卡会员有什么权益",
     "must_contain": ["金卡", "免邮券"]},
    {"id": "rag_016", "category": "membership_faq", "query": "怎么联系人工客服",
     "must_contain": ["转人工"]},
    # 产品：机器人 Pro
    {"id": "rag_017", "category": "product_robot_pro", "query": "智能客服机器人Pro多少钱",
     "must_contain": ["1999", "智能客服机器人 Pro"]},
    {"id": "rag_018", "category": "product_robot_pro", "query": "机器人Pro支持多少路并发",
     "must_contain": ["50 路并发"]},
    {"id": "rag_019", "category": "product_robot_pro", "query": "机器人Pro怎么部署",
     "must_contain": ["SaaS", "无需本地部署"]},
    # 产品：知识库增强包
    {"id": "rag_020", "category": "product_kb_pack", "query": "知识库增强包多少钱",
     "must_contain": ["399", "知识库增强包"]},
    {"id": "rag_021", "category": "product_kb_pack", "query": "知识库增强包能无理由退款吗",
     "must_contain": ["不支持无理由退款", "虚拟服务"]},
    {"id": "rag_022", "category": "product_kb_pack", "query": "知识库增强包能单独使用吗",
     "must_contain": ["依赖", "不能独立运行"]},
]


# --------------------------------------------------------------------------- #
# 入库
# --------------------------------------------------------------------------- #
def ingest_knowledge(client, collection: str) -> int:
    """分块 + 构建稀疏向量，写入 Qdrant（仅 bm25 腿，无需 embedding）。

    分块改用策略模式：按 doc_type / markdown 取 MarkdownChunkingStrategy。
    """
    # 重建稀疏专用集合（与生产集合 schema 解耦）
    real = client._client
    if real.collection_exists(collection):
        real.delete_collection(collection)
    real.create_collection(
        collection_name=collection,
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF)
        },
    )
    client.collection_name = collection

    total = 0
    for fname, doc_type in DOC_TYPE_MAP.items():
        path = KNOWLEDGE_DIR / fname
        if not path.exists():
            print(f"[warn] 知识文档缺失: {path}")
            continue
        text = path.read_text(encoding="utf-8")
        strategy = get_chunking_strategy(doc_type, "markdown")
        chunks = strategy.chunk(text, doc_type=doc_type, source=fname)
        points = []
        for ch in chunks:
            points.append(
                {
                    "id": str(uuid.uuid4()),
                    "vector": {"bm25": build_sparse_vector(ch.content)},
                    "payload": {
                        "content": ch.content,
                        "doc_type": ch.doc_type,
                        "heading_path": ch.heading_path,
                        "metadata": {"source": fname, "heading_path": ch.heading_path},
                    },
                }
            )
        if points:
            client.upsert(points)
            total += len(points)
        print(f"[ingest] {fname}: {len(chunks)} 块 / {len(text)} 字")
    return total


# --------------------------------------------------------------------------- #
# 评估
# --------------------------------------------------------------------------- #
def run_eval(client, top_k: int, min_score: float) -> dict:
    strategy = BM25Strategy(client=client, min_score_threshold=min_score, top_k=top_k)

    rows: list[dict] = []
    agg = {"facts": 0, "h1": 0, "h3": 0, "h5": 0}

    for case in CASES:
        docs = strategy.retrieve(case["query"])  # 已按分数降序，且经阈值过滤
        contents = [d.content for d in docs]
        facts = case["must_contain"]
        hit1 = sum(1 for f in facts if f in "".join(contents[:1]))
        hit3 = sum(1 for f in facts if f in "".join(contents[:3]))
        hit5 = sum(1 for f in facts if f in "".join(contents[:5]))

        agg["facts"] += len(facts)
        agg["h1"] += hit1
        agg["h3"] += hit3
        agg["h5"] += hit5

        top_source = ""
        if docs:
            md = docs[0].metadata or {}
            top_source = f"{md.get('source', '?')} / {'>'.join(md.get('heading_path', []) or [])}"
        rows.append(
            {
                "id": case["id"],
                "category": case["category"],
                "query": case["query"],
                "facts": len(facts),
                "hit5": hit5,
                "recall5": round(hit5 / len(facts), 4) if facts else 1.0,
                "retrieved": len(docs),
                "top_source": top_source,
            }
        )
    return {"rows": rows, "agg": agg}


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def build_report(result: dict, top_k: int, chunks: int) -> str:
    rows = result["rows"]
    agg = result["agg"]
    r1 = agg["h1"] / agg["facts"] if agg["facts"] else 0
    r3 = agg["h3"] / agg["facts"] if agg["facts"] else 0
    r5 = agg["h5"] / agg["facts"] if agg["facts"] else 0

    # 按类别聚合
    by_cat: dict[str, dict] = {}
    for r in rows:
        c = by_cat.setdefault(r["category"], {"facts": 0, "h5": 0, "n": 0, "fail": 0})
        c["facts"] += r["facts"]
        c["h5"] += r["hit5"]
        c["n"] += 1
        if r["recall5"] < 1.0:
            c["fail"] += 1

    lines: list[str] = []
    lines.append("# RAG 检索质量评估报告（BM25 腿）\n")
    lines.append(f"- 检索策略：`bm25`（当前 `rag.retrieval_strategy` 配置）")
    lines.append(f"- 入库块数：{chunks}（来自 `template/knowledge` 8 篇文档）")
    lines.append(f"- top_k：{top_k}；BM25 阈值：{get_rag_config_service().config.min_score_threshold}")
    lines.append(f"- 用例数：{len(rows)}；无需 embedding / LLM，端到端命中本地 Qdrant\n")
    lines.append("## 一、总体召回\n")
    lines.append("| 指标 | 数值 |")
    lines.append("| --- | --- |")
    lines.append(f"| recall@1 | **{r1*100:.2f}%** |")
    lines.append(f"| recall@3 | **{r3*100:.2f}%** |")
    lines.append(f"| recall@5 | **{r5*100:.2f}%** |")
    lines.append(f"| 关键事实总数 / 命中@5 | {agg['facts']} / {agg['h5']} |")
    lines.append("")
    lines.append("## 二、按知识文档（类别）\n")
    lines.append("| 文档 | 用例数 | 事实数 | 命中@5 | recall@5 | 未满分用例 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for cat, c in by_cat.items():
        rc = c["h5"] / c["facts"] if c["facts"] else 0
        lines.append(
            f"| {cat} | {c['n']} | {c['facts']} | {c['h5']} | {rc*100:.2f}% | {c['fail']} |"
        )
    lines.append("")
    lines.append("## 三、逐用例明细\n")
    lines.append("| id | 文档 | query | 事实数 | 命中@5 | recall@5 | 召回块数 | 首块来源 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['category']} | {r['query']} | {r['facts']} | "
            f"{r['hit5']} | {r['recall5']*100:.0f}% | {r['retrieved']} | {r['top_source']} |"
        )
    lines.append("")
    lines.append("## 四、说明与后续\n")
    lines.append("- 本评估仅覆盖 BM25 腿：当前 `embedding.api_key` 为空、策略为 `bm25`。")
    lines.append("- 中文按字切分（MVP 分词），口语化同义问法召回依赖字重叠，长尾问法可能漏召。")
    lines.append("- 若启用 semantic / hybrid，需先填 `embedding.api_key` 并重新入库稠密向量；")
    lines.append("  届时本脚本可扩展为对 semantic / hybrid 策略分别评估（替换 `BM25Strategy`）。")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=None)
    ap.add_argument("--no-ingest", action="store_true", help="复用已存在的 eval 集合，跳过入库")
    ap.add_argument("--report", type=str, default=str(ROOT / "eval" / "rag" / "rag_eval_report.md"))
    args = ap.parse_args()

    cfg = get_rag_config_service().config
    top_k = args.top_k or cfg.top_k
    min_score = cfg.min_score_threshold

    client = get_qdrant_client()

    if args.no_ingest:
        client.collection_name = EVAL_COLLECTION
        chunks = -1
        print(f"[skip] 复用集合 {EVAL_COLLECTION}")
    else:
        chunks = ingest_knowledge(client, EVAL_COLLECTION)
        print(f"[ingest] 共入库 {chunks} 块 -> {EVAL_COLLECTION}")

    result = run_eval(client, top_k=top_k, min_score=min_score)
    report = build_report(result, top_k=top_k, chunks=chunks)

    Path(args.report).write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"\n[done] 报告已写入 {args.report}")


if __name__ == "__main__":
    main()
