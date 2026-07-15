"""RAGAS 直评脚本（eval/rag/run_ragas_eval.py）。

直接用 RAGAS 评测本项目 RAG，**无独立白盒 harness、无入库步骤**：

    三策略检索(retrieved_contexts)  →  项目 LLM 网关生成 response
             →  RAGAS 裁判（检索段 ContextRecall/ContextPrecision + 生成段 Faithfulness/AnswerRelevancy）

知识库入库由前端 `/knowledge/upload` 完成，本脚本只读取已存在的集合（默认生产集合
`customer_service_knowledge`），不负责写入。**一次运行同时产出检索段（白盒）+ 生成段
（黑盒）分数**。检索质量的「便宜可复现」需求由 RAGAS 自带的 Non-LLM / ID 计算后端满足
（--retrieval-backend）。

依赖：
- ragas 0.4.3 仅兼容 langchain 0.3.x（import 时加载 `langchain_community.chat_models.vertexai`，
  该模块在 langchain-community 0.4+ 被移除）。主程序环境为 langchain 1.x，故评测须用独立 venv：
  `python3 -m venv eval/rag/.venv && eval/rag/.venv/bin/python -m pip install -r requirements.txt`
  运行时：`eval/rag/.venv/bin/python eval/rag/run_ragas_eval.py ...`
- Qdrant 在线（集合已由前端上传）；LLM 网关（judge + 生成）；可选 embedding 端点（AnswerRelevancy）
- 详见 eval/rag/eval_rag.md

注意（落地第一坑）：项目 LLM 网关对 thinking 敏感。本脚本通过 `LLMConfig.generation_kwargs()`
（默认 enable_thinking=False → extra_body）统一下发，并对 RAGAS 共用的 AsyncOpenAI client
打补丁强制 enable_thinking=False，避免裁判/生成调用 400 或超时。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.business.rag.retrieval.bm25 import BM25Strategy  # noqa: E402
from app.business.rag.retrieval.semantic import SemanticStrategy  # noqa: E402
from app.business.rag.retrieval.hybrid import HybridStrategy  # noqa: E402
from app.config.rag_config import get_rag_config_service, load_embedding_config_raw  # noqa: E402
from app.config.llm import load_llm_config  # noqa: E402
from app.pkgs.vector import get_qdrant_client  # noqa: E402
from app.business.rag.ingestion import build_embedding_client  # noqa: E402
from app.business.rag.retrieval.rerank import (  # noqa: E402
    RerankClient,
    build_rerank_client,
)

from openai import AsyncOpenAI, OpenAI  # noqa: E402
from ragas.llms import llm_factory  # noqa: E402
from ragas.embeddings.base import embedding_factory  # noqa: E402
from ragas.metrics.collections import (  # noqa: E402
    ContextRecall,
    ContextPrecision,
    Faithfulness,
    AnswerRelevancy,
)

DEFAULT_COLLECTION = "customer_service_knowledge"

RAG_SYSTEM_PROMPT = (
    "你是电商智能客服助手。仅依据下方【参考资料】回答用户问题，"
    "不编造资料之外的信息；资料未覆盖时如实说明无法回答。"
)


# --------------------------------------------------------------------------- #
# 检索策略
# --------------------------------------------------------------------------- #
def build_strategies(client, cfg):
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
    best: dict[str, object] = {}
    for d in docs:
        key = (d.content or "").strip()
        if not key:
            continue
        if key not in best or d.score > best[key].score:
            best[key] = d
    return list(best.values())


def _rerank_docs(rerank_client: RerankClient, query: str, docs: list) -> list:
    """用 rerank 客户端对检索结果重排（仅增强项，失败降级为原始顺序，不丢结果）。"""
    if not docs:
        return docs
    try:
        scored = rerank_client.rerank(query, [d.content for d in docs])
    except Exception as e:
        print(f"[rerank] 调用失败，降级为原始顺序: {e}")
        return docs
    ordered: list = []
    seen: set = set()
    for idx, _score in scored:
        if 0 <= idx < len(docs) and id(docs[idx]) not in seen:
            ordered.append(docs[idx])
            seen.add(id(docs[idx]))
    for d in docs:  # 补回 rerank 未覆盖的块，避免丢结果
        if id(d) not in seen:
            ordered.append(d)
    return ordered or docs


def _preflight_dimension_check(qdrant) -> None:
    """检索前校验集合稠密向量维度与 embedding 模型实际输出是否一致。

    不一致时 Qdrant 会在 query 时返回 400（expected dim: X, got Y）。提前拦截并给出
    可操作提示，避免在海量 case 跑完后才因首条语义检索失败而崩溃。
    """
    emb = build_embedding_client()
    if emb is None:
        return  # 未配 embedding → semantic/hybrid 被跳过，无需校验
    model_dim = len(emb.embed_one("dimension probe"))
    if not qdrant._client.collection_exists(qdrant.collection_name):
        return  # 集合尚未创建（前端未上传），由首次 upsert 建表，维度以 config 为准
    info = qdrant._client.get_collection(qdrant.collection_name)
    coll_dim = info.config.params.vectors.get("dense").size
    if coll_dim != model_dim:
        print(
            f"[ERR] 向量维度不一致：集合 dense={coll_dim}，但 embedding 模型输出 {model_dim}。\n"
            f"      请确认 config/llm_config.local.yml 中 qdrant.vector_size 与 embedding.vector_size\n"
            f"      均等于模型实际输出维度（当前应为 {model_dim}），并删除旧集合后由前端重新上传。"
        )
        sys.exit(1)


# --------------------------------------------------------------------------- #
# 生成（项目 LLM 网关，对 query + contexts 真实生成 response）
# --------------------------------------------------------------------------- #
def _patch_thinking_off(client: AsyncOpenAI, enable: bool = False) -> None:
    """强制所有 chat completion 请求带 enable_thinking，规避网关 400/超时。

    同时作用于本项目生成调用与 RAGAS 内部裁判调用（共用同一 client）。
    """
    original = client.chat.completions.create

    async def wrapped(*args, **kwargs):
        eb = dict(kwargs.get("extra_body") or {})
        eb["enable_thinking"] = enable
        kwargs["extra_body"] = eb
        return await original(*args, **kwargs)

    client.chat.completions.create = wrapped


async def generate_response(client: AsyncOpenAI, cfg, query: str, contexts: list[str]) -> str:
    ctx = "\n\n".join(f"[{i + 1}] {c}" for i, c in enumerate(contexts))
    messages = [
        {"role": "system", "content": RAG_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"【参考资料】\n{ctx}\n\n【用户问题】\n{query}",
        },
    ]
    gen = cfg.generation_kwargs()  # 含 extra_body(enable_thinking=False)
    resp = await client.chat.completions.create(model=cfg.model, messages=messages, **gen)
    return (resp.choices[0].message.content or "").strip()


# --------------------------------------------------------------------------- #
# RAGAS 裁判
# --------------------------------------------------------------------------- #
async def judge(case: dict, contexts: list[str], response: str, llm, emb, backend: str, retrieved_ids: list[str] | None = None) -> dict:
    q = case["query"]
    ref = case.get("reference", "")

    async def _llm():
        rc = await ContextRecall(llm=llm).ascore(
            user_input=q, reference=ref, retrieved_contexts=contexts
        )
        pc = await ContextPrecision(llm=llm).ascore(
            user_input=q, reference=ref, retrieved_contexts=contexts
        )
        return round(rc.value, 4), round(pc.value, 4)

    async def _nonllm():
        from ragas.metrics import NonLLMContextRecall, NonLLMContextPrecisionWithReference

        refc = case.get("reference_contexts", [])
        if not refc:
            return None, None
        rc = NonLLMContextRecall()
        pc = NonLLMContextPrecisionWithReference()
        r = await rc.single_turn_ascore(
            _sample(user_input=q, reference_contexts=refc, retrieved_contexts=contexts)
        )
        p = await pc.single_turn_ascore(
            _sample(user_input=q, reference_contexts=refc, retrieved_contexts=contexts)
        )
        # nonllm/id 的 single_turn_ascore 直接返回 float 分值（非 MetricOutput）
        return round(float(r), 4), round(float(p), 4)

    async def _id():
        from ragas.metrics import IDBasedContextRecall, IDBasedContextPrecision

        refi = case.get("reference_context_ids", [])
        if not refi or not retrieved_ids:
            return None, None
        rc = IDBasedContextRecall()
        pc = IDBasedContextPrecision()
        r = await rc.single_turn_ascore(
            _sample(user_input=q, reference_context_ids=refi, retrieved_context_ids=retrieved_ids)
        )
        p = await pc.single_turn_ascore(
            _sample(user_input=q, reference_context_ids=refi, retrieved_context_ids=retrieved_ids)
        )
        return round(float(r), 4), round(float(p), 4)

    backends = ("llm", "nonllm", "id") if backend == "all" else (backend,)
    result: dict = {}
    for b in backends:
        fn = {"llm": _llm, "nonllm": _nonllm, "id": _id}[b]
        rcr, pcr = await fn()
        suffix = "" if b == "llm" else f"_{b}"
        result[f"context_recall{suffix}"] = rcr
        result[f"context_precision{suffix}"] = pcr

    # 生成段（黑盒）
    faith = await Faithfulness(llm=llm).ascore(
        user_input=q, response=response, retrieved_contexts=contexts
    )
    result["faithfulness"] = round(faith.value, 4)
    if emb is not None:
        relev = await AnswerRelevancy(llm=llm, embeddings=emb).ascore(
            user_input=q, response=response
        )
        result["answer_relevancy"] = round(relev.value, 4)
    else:
        result["answer_relevancy"] = None

    return result


def _sample(**kwargs):
    from ragas.dataset_schema import SingleTurnSample

    return SingleTurnSample(**kwargs)


def _backup_existing_report(out_dir: Path) -> None:
    """每次写新报告前，先把旧的报告/结果按时间戳备份，避免覆盖丢失历史。

    备份文件命名 `<原名>.<YYYYMMDD_HHMMSS>.bak`，与实时产物同目录。
    """
    ts = time.strftime("%Y%m%d_%H%M%S")
    for name in ("ragas_eval_results.json", "ragas_eval_report.md"):
        src = out_dir / name
        if src.exists():
            dst = out_dir / f"{name}.{ts}.bak"
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"[backup] {name} -> {dst.name}")


def _write_markdown_report(results: dict, path: Path) -> None:
    """将评测结果渲染为可读的 Markdown 评估报告（指标列随后端动态生成）。"""
    cfg = results.get("config", {})
    meta_cols = {"id", "query", "expected_doc"}
    metric_cols: list[str] = []
    for blk in results.get("strategies", {}).values():
        for c in blk.get("cases", []):
            for k in c:
                if k in meta_cols:
                    continue
                if k not in metric_cols:
                    metric_cols.append(k)

    lines: list[str] = []
    lines.append("# RAGAS 评测报告")
    lines.append("")
    lines.append(f"- 集合：`{cfg.get('collection')}`")
    lines.append(f"- 截断 k：`{cfg.get('k')}`")
    lines.append(f"- 检索段后端：`{cfg.get('retrieval_backend')}`")
    lines.append(f"- 耗时：`{cfg.get('elapsed_sec')}s`")
    lines.append("")
    lines.append("## 各策略汇总")
    lines.append("")
    lines.append("| 策略 | 样本数 | 失败 | " + " | ".join(metric_cols) + " |")
    lines.append("| --- | ---: | ---: | " + " | ".join(["---:"] * len(metric_cols)) + " |")
    for name, blk in results.get("strategies", {}).items():
        s = blk.get("summary", {})
        cells = [f"{s.get(col, 0)}" for col in metric_cols]
        lines.append(f"| {name} | {s.get('n', 0)} | {s.get('n_failed', 0)} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## 逐 Case 明细")
    lines.append("")
    for name, blk in results.get("strategies", {}).items():
        lines.append(f"### 策略：{name}")
        lines.append("")
        lines.append("| Case | Query | ExpectedDoc | " + " | ".join(metric_cols) + " |")
        lines.append("| --- | --- | --- | " + " | ".join(["---:"] * len(metric_cols)) + " |")
        for c in blk.get("cases", []):
            cells = [f"{c.get(col)}" for col in metric_cols]
            lines.append(
                f"| {c.get('id')} | {c.get('query')} | {c.get('expected_doc')} | "
                + " | ".join(cells) + " |"
            )
        lines.append("")
    lines.append(
        "> 指标说明：ContextRecall / ContextPrecision 反映检索质量（白盒），后缀 `_llm` / `_nonllm` / "
        "`_id` 表示覆盖计算后端（llm=语义claims；nonllm=字符串相似度；id=文档块ID精确匹配）；"
        "Faithfulness 反映回答是否忠于检索内容；AnswerRelevancy 反映回答相关性（黑盒）。"
        "分值 0~1，越高越好。"
    )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
async def main() -> None:
    parser = argparse.ArgumentParser(description="RAGAS 直评本项目 RAG")
    parser.add_argument("--cases", default=str(Path(__file__).resolve().parent / "rag_eval_cases.json"))
    parser.add_argument("--k", type=int, default=None, help="评估截断 k（默认取 rag.top_k）")
    parser.add_argument(
        "--strategies", default="bm25,semantic,hybrid",
        help="启用的检索策略，逗号分隔；未配 embedding 时 semantic/hybrid 自动跳过",
    )
    parser.add_argument("--limit", type=int, default=None, help="仅评前 N 条 case")
    parser.add_argument(
        "--collection", default=DEFAULT_COLLECTION,
        help=f"评测所用 Qdrant 集合（由前端 /knowledge/upload 入库，本脚本只读）；默认 {DEFAULT_COLLECTION}",
    )
    parser.add_argument(
        "--retrieval-backend", default="llm",
        help="检索段计算后端：llm（语义claims）| nonllm（字符串相似度，需 reference_contexts）"
             "| id（文档块ID精确匹配，需 reference_context_ids）| all（一次性算三种后端）",
    )
    parser.add_argument(
        "--concurrency", type=int, default=4,
        help="并发评测 case 数（默认 4，同步 retrieve 走 to_thread 避免阻塞事件循环）",
    )
    parser.add_argument(
        "--rerank", action="store_true",
        help="对检索结果施加 rerank（用配置段 rag.rerank 的 model/api_key/base_url）；"
             "无可用 rerank 端点时优雅降级为原始顺序。默认跟随 rag.rerank.enabled。",
    )
    parser.add_argument(
        "--no-rerank", action="store_true",
        help="强制关闭 rerank（即便配置 rag.rerank.enabled=true），用于对照实验。",
    )
    args = parser.parse_args()

    cases_path = Path(args.cases)
    if not cases_path.exists():
        print(f"[ERR] 评测集不存在：{cases_path}（请先准备 rag_eval_cases.json，含 reference 字段）")
        sys.exit(1)
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[: args.limit]

    cfg = get_rag_config_service().get_config()
    k = args.k or cfg.top_k

    # LLM client（judge + 生成，共用）→ 强制 thinking off
    llm_cfg = load_llm_config()
    client = AsyncOpenAI(base_url=llm_cfg.base_url, api_key=llm_cfg.api_key)
    _patch_thinking_off(client, enable=False)
    # ragas 结构化输出（如 Faithfulness 的 statements 长 JSON）易触达默认 max_tokens 上限而截断，
    # 显式抬高到 8192，避免 InstructorRetryException（max_tokens length limit）。
    llm = llm_factory(llm_cfg.model, client=client, max_tokens=8192)

    # AnswerRelevancy 嵌入：复用项目 embedding 配置（与入库同源），而非 LLM 网关的
    # text-embedding-3-small。AnswerRelevancy 内部直接 await aembed_text，必须用异步
    # AsyncOpenAI client（自建独立 client 指向 embedding 网关，不共享 LLM client）。
    emb_cfg = load_embedding_config_raw()
    if not emb_cfg.get("api_key"):
        print("[WARN] 未配置 embedding，跳过 AnswerRelevancy（其余指标正常）")
        emb = None
    else:
        emb_client = AsyncOpenAI(
            base_url=emb_cfg.get("base_url", "") or None,
            api_key=emb_cfg["api_key"],
        )
        emb_model = emb_cfg.get("model", "text-embedding-v4")
        emb = embedding_factory("openai", model=emb_model, client=emb_client)

    # 集合（由前端 /knowledge/upload 入库，本脚本只读，不写入）
    qdrant = get_qdrant_client()
    qdrant.collection_name = args.collection
    _preflight_dimension_check(qdrant)

    # 策略
    all_strategies = build_strategies(qdrant, cfg)
    wanted = [s.strip() for s in args.strategies.split(",") if s.strip()]
    active = {name: s for name, s in all_strategies.items() if name in wanted}
    if not active:
        print("[ERR] 没有可用的检索策略")
        sys.exit(1)

    # 按 eval/rag/eval_rag.md §9「三策略初始配置」分别设定阈值（评估起点）。
    # 单一全局 min_score_threshold 跨策略直套会返回空结果（见 §9 规则①）：
    #   - bm25    量纲 0~10（初始 4）
    #   - semantic 余弦 0~1（初始 0.0）
    #   - hybrid   RRF 融合分（必须 0.0）
    # build_strategies 把同一阈值套到所有策略，故此处按策略覆盖。
    STRATEGY_INIT = {
        "bm25": {"min_score_threshold": 4.0},
        "semantic": {"min_score_threshold": 0.0},
        "hybrid": {"min_score_threshold": 0.0, "top_k": 6},
    }

    def _apply_init(strat, init):
        for attr, val in init.items():
            if hasattr(strat, attr):
                setattr(strat, attr, val)
        subs = getattr(strat, "strategies", None)
        if subs:  # hybrid 内含 bm25 + semantic 子策略，需递归覆盖
            for sub in subs:
                _apply_init(sub, init)

    for name, strat in active.items():
        if name in STRATEGY_INIT:
            _apply_init(strat, STRATEGY_INIT[name])
            init = STRATEGY_INIT[name]
            print(f"[init] {name}: " + ", ".join(f"{a}={init[a]}" for a in init))

    t0 = time.time()
    per_strategy: dict[str, dict] = {}
    sem = asyncio.Semaphore(args.concurrency)

    # rerank（可选增强）：接进 eval 检索路径，使 item 2 可被度量。
    # 优先级：--no-rerank 强制关 → --rerank 强制用配置段（需 api_key）→ 否则跟随 rag.rerank.enabled。
    rerank_client = None
    if args.no_rerank:
        print("[rerank] 按 --no-rerank 强制关闭（对照实验）")
    elif args.rerank:
        rc = cfg.rerank
        if rc.api_key:
            rerank_client = RerankClient(
                api_key=rc.api_key,
                model=rc.model,
                base_url=rc.base_url,
            )
            print(f"[rerank] 启用（--rerank，model={rc.model}）")
        else:
            print("[WARN] --rerank 已指定但 rag.rerank.api_key 为空，跳过重排")
    elif cfg.rerank.enabled:
        rerank_client = build_rerank_client()
        if rerank_client:
            print(f"[rerank] 按配置启用（model={cfg.rerank.model}）")

    async def run_case(strat, c):
        async with sem:
            kk = getattr(strat, "top_k", k)
            # retrieve 是同步方法（内部 embed_one 走网络），用 to_thread 避免阻塞事件循环，
            # 从而让多 case 的异步 LLM 调用可以重叠。
            try:
                docs = dedup(await asyncio.to_thread(strat.retrieve, c["query"], None))
                if rerank_client is not None:
                    docs = await asyncio.to_thread(_rerank_docs, rerank_client, c["query"], docs)
                docs = docs[:kk]
            except Exception as e:  # 检索异常（如 embedding 失败）不中断整轮
                return {"id": c["id"], "query": c["query"], "expected_doc": c["expected_doc"],
                        "_failed": True, "_reason": f"retrieve_error: {e}"}
            contexts = [d.content for d in docs]
            retrieved_ids = [str(d.id) for d in docs]
            if not contexts:
                # 检索被阈值过滤为空，RAGAS 无法在空上下文上计算，标记跳过而非抛错中断整轮。
                return {"id": c["id"], "query": c["query"], "expected_doc": c["expected_doc"],
                        "_failed": True, "_reason": "retrieved_contexts empty (阈值过滤为空)"}
            try:
                response = await generate_response(client, llm_cfg, c["query"], contexts)
                m = await judge(c, contexts, response, llm, emb, args.retrieval_backend, retrieved_ids)
            except Exception as e:  # 单 case 评测异常（如网关超时）不中断整轮
                return {"id": c["id"], "query": c["query"], "expected_doc": c["expected_doc"],
                        "_failed": True, "_reason": f"judge_error: {e}"}
            m["id"] = c["id"]
            m["query"] = c["query"]
            m["expected_doc"] = c["expected_doc"]
            return m

    for name, strat in active.items():
        print(f"\n=== 策略：{name} ===")
        case_results = []
        failed: list[str] = []
        agg = defaultdict(list)
        gathered = await asyncio.gather(
            *(run_case(strat, c) for c in cases), return_exceptions=True
        )
        for c, res in zip(cases, gathered):
            if isinstance(res, Exception):
                print(f"  [{c['id']}] [FAILED] 未捕获异常：{res}")
                failed.append(c["id"])
                continue
            if res.get("_failed"):
                print(f"  [{c['id']}] [SKIP] {res['_reason']}")
                failed.append(c["id"])
                continue
            m = res
            case_results.append(m)
            for key, val in m.items():
                if key in ("id", "query", "expected_doc") or val is None:
                    continue
                agg[key].append(val)
            row = " ".join(
                f"{kk}={m[kk]}" for kk in m if kk not in ("id", "query", "expected_doc")
            )
            print(f"  [{c['id']}] {row}")

        summary = {key: round(sum(v) / len(v), 4) if v else 0.0 for key, v in agg.items()}
        summary["n"] = len(case_results)
        summary["n_total"] = len(cases)
        summary["n_failed"] = len(failed)
        per_strategy[name] = {"summary": summary, "cases": case_results}
        summ_parts = " ".join(f"{kk}={summary[kk]}" for kk in summary)
        print(f"  {summ_parts}")

    elapsed = time.time() - t0
    out_dir = Path(__file__).resolve().parent
    _backup_existing_report(out_dir)
    results = {
        "config": {
            "k": k,
            "retrieval_backend": args.retrieval_backend,
            "collection": args.collection,
            "elapsed_sec": round(elapsed, 2),
        },
        "strategies": per_strategy,
    }
    res_path = out_dir / "ragas_eval_results.json"
    res_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = out_dir / "ragas_eval_report.md"
    _write_markdown_report(results, report_path)
    print(f"\n[OK] 结果 -> {res_path}（耗时 {elapsed:.1f}s）")
    print(f"[OK] 报告 -> {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
