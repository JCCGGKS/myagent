from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.business.rag.chunking.models import Chunk


class BaseChunkingStrategy(ABC):
    """分块策略抽象基类（策略模式，参考 retrieval_strategy.RetrievalStrategy）。

    所有分块策略继承本类，统一接口 ``chunk(...)``；具体切法（结构 / 递归字符 /
    行级 / 条款）由子类决定。编排层（ingestion）只依赖此抽象与 registry 工厂，
    新增文档格式 = 加一行注册 + 新建一个策略文件，编排层零改动。
    """

    @abstractmethod
    def chunk(
        self,
        text: str,
        *,
        doc_type: str = "unknown",
        source: str = "",
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        min_chunk_size: int = 50,
        **kwargs: Any,
    ) -> list[Chunk]:
        """把一份文档切成 Chunk 列表。

        Args:
            text: 待切块文本（已由对应 parser 抽取为纯文本）。
            doc_type: 内容类型（faq / policy / product ...），优先于 doc_format 命中策略。
            source: 来源标识（文件名 / JSON 元数据），透传进 chunk.metadata。
            chunk_size: 单块最大字符数。
            chunk_overlap: 兜底滑窗重叠字符数（仅在 _hard_split 兜底层生效）。
            min_chunk_size: 兜底切出的最短块长度，短于此丢弃。
        """
        ...
