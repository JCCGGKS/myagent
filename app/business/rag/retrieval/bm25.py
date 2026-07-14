from __future__ import annotations

from app.business.rag.retrieval.base import RetrievalStrategy
from app.business.rag.retrieval.models import Document, documents_from_hits
from app.pkgs.vector import QdrantClient
from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("rag")


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
        filtered = documents_from_hits(results, self.min_score_threshold)
        logger.info(_tagged("rag", "BM25 retrieve end raw=%d filtered=%d"), len(results), len(filtered))
        return filtered
