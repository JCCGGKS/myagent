from __future__ import annotations

from typing import Any

from app.config.rag_config import RagConfig
from app.business.rag.retrieval.base import RetrievalStrategy
from app.business.rag.retrieval.bm25 import BM25Strategy
from app.business.rag.retrieval.semantic import SemanticStrategy
from app.business.rag.retrieval.hybrid import HybridStrategy
from app.pkgs.vector import QdrantClient, get_qdrant_client


def get_strategy_from_config(rag_config: RagConfig | None = None) -> RetrievalStrategy:
    """从 RAG 配置创建对应检索策略实例。

    rag_config 为 None 时，从运行时 RagConfigService 读取最新配置。
    """
    from app.config.rag_config import get_rag_config_service

    if rag_config is None:
        rag_config = get_rag_config_service().get_config()

    client = get_qdrant_client()
    return _build_strategy(client, rag_config)


def _build_embedding_client() -> Any:
    """构建语义检索所需的真实 EmbeddingClient（缺失配置时抛错）。"""
    from app.business.rag.ingestion import build_embedding_client

    embedding_client = build_embedding_client()
    if embedding_client is None:
        raise RuntimeError(
            "未配置 embedding.api_key，无法进行语义/混合检索。"
            "请在 config/llm_config.{env}.yml 的顶层 embedding 段配置 model/api_key。"
        )
    return embedding_client


def _build_strategy(client: QdrantClient, rag_config: RagConfig) -> RetrievalStrategy:
    """根据 RagConfig 构建具体检索策略。

    min_score_threshold 为单一字段（rag 顶层），直接读出即用，不做归一化映射。
    同一阈值会同时作用于 bm25 / semantic 的单路过滤与 hybrid 的融合后过滤。
    前端按 retrieval_strategy 控制可输入范围，避免量纲不匹配（如 hybrid 误设高分）。
    """
    retrieval_strategy = rag_config.retrieval_strategy
    threshold = rag_config.min_score_threshold
    top_k = rag_config.top_k

    if retrieval_strategy == "bm25":
        return BM25Strategy(
            client=client,
            min_score_threshold=threshold,
            top_k=top_k,
        )
    elif retrieval_strategy == "semantic":
        return SemanticStrategy(
            client=client,
            embedding_client=_build_embedding_client(),
            min_score_threshold=threshold,
            top_k=top_k,
        )
    else:  # hybrid
        return HybridStrategy(
            strategies=[
                BM25Strategy(client=client, min_score_threshold=threshold, top_k=top_k),
                SemanticStrategy(
                    client=client,
                    embedding_client=_build_embedding_client(),
                    min_score_threshold=threshold,
                    top_k=top_k,
                ),
            ],
            min_score_threshold=threshold,
            top_k=top_k,
            rrf_k=rag_config.rrf_k,
        )
