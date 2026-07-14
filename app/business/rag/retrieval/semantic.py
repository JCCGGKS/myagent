from __future__ import annotations

from typing import Any

from app.business.rag.retrieval.base import RetrievalStrategy
from app.business.rag.retrieval.models import Document, documents_from_hits
from app.pkgs.vector import QdrantClient
from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("rag")


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
        filtered = documents_from_hits(results, self.min_score_threshold)
        logger.info(_tagged("rag", "Semantic retrieve end raw=%d filtered=%d"), len(results), len(filtered))
        return filtered
