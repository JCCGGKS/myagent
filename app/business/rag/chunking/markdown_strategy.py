from __future__ import annotations

from typing import Any

from app.business.rag.chunking.base import BaseChunkingStrategy
from app.business.rag.chunking.models import Chunk
from app.business.rag.chunking.recursive_splitter import RecursiveSplitter
from app.business.rag.chunking.structure_chunk import chunk_markdown_text


class MarkdownChunkingStrategy(BaseChunkingStrategy):
    """Markdown 分块：解析 ``#``~``######`` 标题树 → 结构切块（当前能力）。

    逻辑块继承 heading_path；超长块由 ``RecursiveSplitter`` 降级。行为对齐
    原 ``chunker.chunk_markdown``，保证改造前后 Markdown 入库无回归。
    """

    def __init__(self, splitter: RecursiveSplitter | None = None) -> None:
        self._splitter = splitter or RecursiveSplitter()

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
        return chunk_markdown_text(
            text,
            doc_type=doc_type,
            source=source,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            splitter=self._splitter,
            min_chunk_size=min_chunk_size,
        )
