from __future__ import annotations

from abc import ABC, abstractmethod

from app.business.rag.retrieval.models import Document


class RetrievalStrategy(ABC):
    """检索策略抽象基类（策略模式，参考 chunking.base.BaseChunkingStrategy）。"""

    @abstractmethod
    def retrieve(self, query: str, user_id: int | None = None) -> list[Document]:
        """执行检索，返回文档列表。user_id 为 None 时不限定用户（全库召回）。"""
        pass


class DisabledRetrievalStrategy(RetrievalStrategy):
    """Qdrant 未启用时的降级策略：检索直接返回空，不连 Qdrant、不报错。

    用于 ``qdrant.enabled: false`` 场景（如未启动 Qdrant 的纯本地/测试环境），
    让聊天链路在缺少向量库时仍可正常运行，仅不再提供知识库召回。
    """

    def retrieve(self, query: str, user_id: int | None = None) -> list[Document]:
        return []
