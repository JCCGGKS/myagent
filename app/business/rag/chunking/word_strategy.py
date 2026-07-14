from __future__ import annotations

from typing import Any

from app.business.rag.chunking.base import BaseChunkingStrategy
from app.business.rag.chunking.models import Chunk
from app.business.rag.chunking.recursive_splitter import RecursiveSplitter
from app.business.rag.chunking.structure_chunk import chunk_markdown_text


class WordChunkingStrategy(BaseChunkingStrategy):
    """Word 分块（近期）：docx parser 先把 .docx 抽成标题树纯文本，本策略复用
    ``structure_chunk`` 与 Markdown 同源（05.3 §3 结论：Word 复用 Markdown 逻辑）。

    当前入口接收的 text 已是 parser 产出的纯文本（含 ``#``~``######`` 标题或
    缩进层级）；parser 层（python-docx 等）在 近期 补齐，策略本身只负责切块。
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
