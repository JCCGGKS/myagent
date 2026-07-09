from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

import yaml

from app.pkgs.vector import get_qdrant_client


class Document:
    """检索结果文档。"""

    def __init__(self, id: str, content: str, metadata: dict[str, Any], score: float) -> None:
        self.id = id
        self.content = content
        self.metadata = metadata
        self.score = score

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "metadata": self.metadata,
            "score": self.score,
        }


class RetrievalStrategy(ABC):
    """检索策略抽象基类。"""

    @abstractmethod
    def retrieve(self, query: str) -> list[Document]:
        """执行检索，返回文档列表。"""
        pass


class BM25Strategy(RetrievalStrategy):
    """BM25 关键词检索策略。"""

    def __init__(self, client: QdrantClient, min_score_threshold: float = 5.0) -> None:
        self.client = client
        self.min_score_threshold = min_score_threshold

    def retrieve(self, query: str) -> list[Document]:
        """执行 BM25 检索。"""
        results = self.client.search_bm25(
            query=query,
            limit=20,  # 多召回一些，后续过滤
        )
        # 过滤低分
        filtered = [
            Document(
                id=hit["id"],
                content=hit["content"],
                metadata=hit["metadata"],
                score=hit["score"],
            )
            for hit in results
            if hit["score"] >= self.min_score_threshold
        ]
        return filtered


class SemanticStrategy(RetrievalStrategy):
    """语义向量检索策略。"""

    def __init__(
        self,
        client: QdrantClient,
        embedding_client: Any,  # EmbeddingClient
        min_score_threshold: float = 0.7,
    ) -> None:
        self.client = client
        self.embedding_client = embedding_client
        self.min_score_threshold = min_score_threshold

    def retrieve(self, query: str) -> list[Document]:
        """执行语义向量检索。"""
        if self.embedding_client is None:
            raise RuntimeError("SemanticStrategy 未配置 embedding_client，无法生成查询向量")
        query_vector = self.embedding_client.embed_one(query)

        # 2. 调用 Qdrant 向量检索（距离度量由集合创建时的 qdrant.distance 固定）
        results = self.client.search_semantic(
            query_vector=query_vector,
            limit=20,
        )

        # 3. 过滤低分
        filtered = [
            Document(
                id=hit["id"],
                content=hit["content"],
                metadata=hit["metadata"],
                score=hit["score"],
            )
            for hit in results
            if hit["score"] >= self.min_score_threshold
        ]
        return filtered


class HybridStrategy(RetrievalStrategy):
    """混合检索策略（BM25 + 语义向量）。"""

    def __init__(
        self,
        bm25_strategy: BM25Strategy,
        semantic_strategy: SemanticStrategy,
        min_score_threshold: float = 0.0,
    ) -> None:
        self.bm25_strategy = bm25_strategy
        self.semantic_strategy = semantic_strategy
        self.min_score_threshold = min_score_threshold

    def retrieve(self, query: str) -> list[Document]:
        """执行混合检索（分别召回后 RRF 融合）。"""
        # 1. 分别召回
        bm25_docs = self.bm25_strategy.retrieve(query)
        semantic_docs = self.semantic_strategy.retrieve(query)

        # 2. RRF 融合（倒数排序融合，量纲无关，固定使用）
        fused = self._rrf_fusion(bm25_docs, semantic_docs)

        # 3. 过滤低分，返回 top_k
        filtered = [doc for doc in fused if doc.score >= self.min_score_threshold]
        return filtered[:20]  # 返回前 20 个

    def _rrf_fusion(
        self, bm25_docs: list[Document], semantic_docs: list[Document], k: int = 60
    ) -> list[Document]:
        """倒数排序融合（RRF）。"""
        # 将 doc id 映射到分数
        scores: dict[str, float] = {}

        # BM25 结果
        for rank, doc in enumerate(bm25_docs, start=1):
            doc_id = doc.id
            if doc_id not in scores:
                scores[doc_id] = 0.0
            scores[doc_id] += 1.0 / (k + rank)

        # 语义向量结果
        for rank, doc in enumerate(semantic_docs, start=1):
            doc_id = doc.id
            if doc_id not in scores:
                scores[doc_id] = 0.0
            scores[doc_id] += 1.0 / (k + rank)

        # 构建融合后的文档列表
        doc_map: dict[str, Document] = {}
        for doc in bm25_docs + semantic_docs:
            if doc.id not in doc_map:
                doc_map[doc.id] = doc

        fused = [
            Document(
                id=doc_id,
                content=doc_map[doc_id].content,
                metadata=doc_map[doc_id].metadata,
                score=score,
            )
            for doc_id, score in scores.items()
        ]
        fused.sort(key=lambda x: x.score, reverse=True)
        return fused


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

    if retrieval_strategy == "bm25":
        return BM25Strategy(
            client=client,
            min_score_threshold=threshold,
        )
    elif retrieval_strategy == "semantic":
        return SemanticStrategy(
            client=client,
            embedding_client=_build_embedding_client(),
            min_score_threshold=threshold,
        )
    else:  # hybrid
        bm25_strategy = BM25Strategy(
            client=client,
            min_score_threshold=threshold,
        )
        semantic_strategy = SemanticStrategy(
            client=client,
            embedding_client=_build_embedding_client(),
            min_score_threshold=threshold,
        )
        return HybridStrategy(
            bm25_strategy=bm25_strategy,
            semantic_strategy=semantic_strategy,
            min_score_threshold=threshold,
        )
