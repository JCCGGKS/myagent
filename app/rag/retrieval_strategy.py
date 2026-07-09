from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

import yaml

from app.rag.qdrant_client import get_qdrant_client


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
        metric: str = "cosine",
    ) -> None:
        self.client = client
        self.embedding_client = embedding_client
        self.min_score_threshold = min_score_threshold
        self.metric = metric

    def retrieve(self, query: str) -> list[Document]:
        """执行语义向量检索。"""
        # TODO: 接入真实 embedding 客户端后，用下面代码
        # query_vector = self.embedding_client.embed(query)
        # 当前为模拟实现，生成随机向量
        import random

        query_vector = [random.random() for _ in range(1024)]  # 模拟 1024 维向量

        # 2. 调用 Qdrant 向量检索
        results = self.client.search_semantic(
            query_vector=query_vector,
            limit=20,
            metric=self.metric,
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
        fusion_method: str = "rrf",  # rrf | weighted
        weighted_alpha: float = 0.5,
        min_score_threshold: float = 0.5,
    ) -> None:
        self.bm25_strategy = bm25_strategy
        self.semantic_strategy = semantic_strategy
        self.fusion_method = fusion_method
        self.weighted_alpha = weighted_alpha
        self.min_score_threshold = min_score_threshold

    def retrieve(self, query: str) -> list[Document]:
        """执行混合检索（分别召回后融合）。"""
        # 1. 分别召回
        bm25_docs = self.bm25_strategy.retrieve(query)
        semantic_docs = self.semantic_strategy.retrieve(query)

        # 2. 融合
        if self.fusion_method == "rrf":
            fused = self._rrf_fusion(bm25_docs, semantic_docs)
        else:
            fused = self._weighted_fusion(bm25_docs, semantic_docs, self.weighted_alpha)

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

    def _weighted_fusion(
        self,
        bm25_docs: list[Document],
        semantic_docs: list[Document],
        alpha: float,
    ) -> list[Document]:
        """加权融合（需归一化分数）。"""
        # 归一化 BM25 分数
        bm25_max = max((doc.score for doc in bm25_docs), default=1.0)
        bm25_min = min((doc.score for doc in bm25_docs), default=0.0)
        bm25_range = bm25_max - bm25_min if bm25_max != bm25_min else 1.0

        # 归一化语义分数（余弦相似度已在 0~1 范围）
        sem_max = max((doc.score for doc in semantic_docs), default=1.0)
        sem_min = min((doc.score for doc in semantic_docs), default=0.0)
        sem_range = sem_max - sem_min if sem_max != sem_min else 1.0

        # 构建融合后的文档列表
        doc_map: dict[str, Document] = {}
        scores: dict[str, float] = {}

        for doc in bm25_docs + semantic_docs:
            if doc.id not in doc_map:
                doc_map[doc.id] = doc

        for doc in bm25_docs:
            doc_id = doc.id
            normalized_score = (doc.score - bm25_min) / bm25_range
            if doc_id not in scores:
                scores[doc_id] = 0.0
            scores[doc_id] += (1 - alpha) * normalized_score

        for doc in semantic_docs:
            doc_id = doc.id
            normalized_score = (doc.score - sem_min) / sem_range
            if doc_id not in scores:
                scores[doc_id] = 0.0
            scores[doc_id] += alpha * normalized_score

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
    retrieval_strategy = rag_config.retrieval_strategy

    if retrieval_strategy == "bm25":
        return BM25Strategy(
            client=client,
            min_score_threshold=rag_config.bm25.min_score_threshold,
        )
    elif retrieval_strategy == "semantic":
        return SemanticStrategy(
            client=client,
            embedding_client=None,  # TODO: 接入真实 embedding 客户端
            min_score_threshold=rag_config.semantic.min_score_threshold,
            metric=rag_config.semantic.metric,
        )
    else:  # hybrid
        bm25_strategy = BM25Strategy(
            client=client,
            min_score_threshold=rag_config.bm25.min_score_threshold,
        )
        semantic_strategy = SemanticStrategy(
            client=client,
            embedding_client=None,  # TODO: 接入真实 embedding 客户端
            min_score_threshold=rag_config.semantic.min_score_threshold,
            metric=rag_config.semantic.metric,
        )
        return HybridStrategy(
            bm25_strategy=bm25_strategy,
            semantic_strategy=semantic_strategy,
            fusion_method=rag_config.hybrid.fusion_method,
            weighted_alpha=rag_config.hybrid.weighted_alpha,
            min_score_threshold=rag_config.hybrid.min_score_threshold,
        )
