from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.config.rag_config import RagConfig
from app.pkgs.vector import QdrantClient, get_qdrant_client
from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("rag")


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
    def retrieve(self, query: str, user_id: int | None = None) -> list[Document]:
        """执行检索，返回文档列表。user_id 为 None 时不限定用户（全库召回）。"""
        pass


class BM25Strategy(RetrievalStrategy):
    """BM25 关键词检索策略。"""

    def __init__(
        self, client: QdrantClient, min_score_threshold: float = 5.0, top_k: int = 5
    ) -> None:
        self.client = client
        self.min_score_threshold = min_score_threshold
        self.top_k = top_k

    def retrieve(self, query: str, user_id: int | None = None) -> list[Document]:
        """执行 BM25 检索。"""
        logger.info(_tagged("rag", "BM25 retrieve start query=%r user_id=%s"), query, user_id)
        results = self.client.search_bm25(
            query=query,
            limit=max(self.top_k * 2, 20),  # 多召回一些，后续过滤
            user_id=user_id,
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
        logger.info(_tagged("rag", "BM25 retrieve end raw=%d filtered=%d"), len(results), len(filtered))
        return filtered


class SemanticStrategy(RetrievalStrategy):
    """语义向量检索策略。"""

    def __init__(
        self,
        client: QdrantClient,
        embedding_client: Any,  # EmbeddingClient
        min_score_threshold: float = 0.7,
        top_k: int = 5,
    ) -> None:
        self.client = client
        self.embedding_client = embedding_client
        self.min_score_threshold = min_score_threshold
        self.top_k = top_k

    def retrieve(self, query: str, user_id: int | None = None) -> list[Document]:
        """执行语义向量检索。"""
        if self.embedding_client is None:
            raise RuntimeError("SemanticStrategy 未配置 embedding_client，无法生成查询向量")
        logger.info(_tagged("rag", "Semantic retrieve start query=%r user_id=%s"), query, user_id)
        query_vector = self.embedding_client.embed_one(query)

        # 2. 调用 Qdrant 向量检索（距离度量由集合创建时的 qdrant.distance 固定）
        results = self.client.search_semantic(
            query_vector=query_vector,
            limit=max(self.top_k * 2, 20),  # 多召回一些，后续过滤
            user_id=user_id,
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
        logger.info(_tagged("rag", "Semantic retrieve end raw=%d filtered=%d"), len(results), len(filtered))
        return filtered


class HybridStrategy(RetrievalStrategy):
    """混合检索策略（多路检索结果 RRF 融合）。通过构造注入子策略，职责单一。"""

    def __init__(
        self,
        strategies: list[RetrievalStrategy],
        min_score_threshold: float = 0.0,
        top_k: int = 5,
        rrf_k: int = 60,
    ) -> None:
        self._strategies = strategies  # 注入任意数量的子策略
        self.min_score_threshold = min_score_threshold
        self.top_k = top_k
        self.rrf_k = rrf_k

    def retrieve(self, query: str, user_id: int | None = None) -> list[Document]:
        """各子策略分别召回，RRF 融合后返回。"""
        logger.info(_tagged("rag", "Hybrid retrieve start strategies=%d query=%r user_id=%s"), len(self._strategies), query, user_id)
        # 1. 各路召回
        results_by_strategy: list[list[Document]] = []
        for strategy in self._strategies:
            results_by_strategy.append(strategy.retrieve(query, user_id=user_id))

        # 2. RRF 融合（量纲无关，支持任意路数）
        fused = self._rrf_fusion(results_by_strategy)

        # 3. 过滤低分，返回缓冲截断结果
        filtered = [doc for doc in fused if doc.score >= self.min_score_threshold]
        logger.info(_tagged("rag", "Hybrid retrieve end fused=%d filtered=%d"), len(fused), len(filtered))
        return filtered[: max(self.top_k * 2, 20)]

    def _rrf_fusion(self, results_by_strategy: list[list[Document]]) -> list[Document]:
        """倒数排序融合（RRF），支持任意数量子策略。"""
        scores: dict[str, float] = {}
        doc_map: dict[str, Document] = {}

        for docs in results_by_strategy:
            for rank, doc in enumerate(docs, start=1):
                if doc.id not in scores:
                    scores[doc.id] = 0.0
                scores[doc.id] += 1.0 / (self.rrf_k + rank)
                if doc.id not in doc_map:
                    doc_map[doc.id] = doc

        fused = [
            Document(id=doc_id, content=doc_map[doc_id].content,
                     metadata=doc_map[doc_id].metadata, score=score)
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
