from __future__ import annotations

from abc import ABC, abstractmethod

from app.business.rag.retrieval.models import Document


class RetrievalStrategy(ABC):
    """检索策略抽象基类（策略模式，参考 chunking.base.BaseChunkingStrategy）。"""

    @abstractmethod
    def retrieve(self, query: str, user_id: int | None = None) -> list[Document]:
        """执行检索，返回文档列表。user_id 为 None 时不限定用户（全库召回）。"""
        pass
