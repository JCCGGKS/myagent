from __future__ import annotations

from app.business.rag.retrieval.base import RetrievalStrategy
from app.business.rag.retrieval.models import Document
from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("rag")


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
