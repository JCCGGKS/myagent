from __future__ import annotations

from typing import Any

from app.business.rag.retrieval.base import RetrievalStrategy
from app.business.rag.retrieval.bm25 import build_sparse_vector
from app.business.rag.retrieval.models import Document, documents_from_hits
from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("rag")


class HybridStrategy(RetrievalStrategy):
    """混合检索策略：dense（语义）+ bm25（关键词）两路，Qdrant 服务端 RRF 融合。

    通过 `client.search_hybrid` 一次请求完成 fusion（prefetch + RrfQuery(rrf=Rrf(k=rrf_k))），
    不再在客户端分两路召回后自写 RRF。语义向量由 embedding_client 产出，
    关键词稀疏向量由 `build_sparse_vector` 产出。
    """

    def __init__(
        self,
        client: Any,
        embedding_client: Any,
        min_score_threshold: float = 0.0,
        top_k: int = 5,
        rrf_k: int = 60,
    ) -> None:
        self.client = client
        self.embedding_client = embedding_client
        self.min_score_threshold = min_score_threshold
        self.top_k = top_k
        self.rrf_k = rrf_k

    def retrieve(self, query: str, user_id: int | None = None) -> list[Document]:
        """dense + bm25 两路 prefetch，Qdrant 服务端 RRF 融合后返回。"""
        logger.info(_tagged("rag", "Hybrid retrieve start query=%r user_id=%s"), query, user_id)
        dense = self.embedding_client.embed_one(query)
        sparse = build_sparse_vector(query)
        hits = self.client.search_hybrid(
            dense_vec=dense,
            sparse_vec=sparse,
            limit=max(self.top_k * 2, 20),
            rrf_k=self.rrf_k,
            user_id=user_id,
        )
        docs = documents_from_hits(hits, None)
        filtered = [doc for doc in docs if doc.score >= self.min_score_threshold]
        logger.info(_tagged("rag", "Hybrid retrieve end fused=%d filtered=%d"), len(docs), len(filtered))
        return filtered[: max(self.top_k * 2, 20)]
