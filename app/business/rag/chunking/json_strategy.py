from __future__ import annotations

from typing import Any

from app.business.rag.chunking.base import BaseChunkingStrategy
from app.business.rag.chunking.models import Chunk
from app.business.rag.chunking.recursive_splitter import RecursiveSplitter


class JsonChunkingStrategy(BaseChunkingStrategy):
    """通用 JSON 记录分块（当前能力）：每对一块（QA / 记录级）。

    迁移自 ``ingest_json_records`` 的切块部分：ingestion 已按记录把非
    ``text_field`` 字段收进 ``source``（json.dumps），本策略对 ``content``
    做递归字符切块，超长再降级。每块 ``metadata={"source": ...}`` 透传记录字段，
    行为对齐改造前的 JSON 入库，保证无回归。
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
        parts = self._splitter.split(text, chunk_size, chunk_overlap, min_chunk_size)
        return [
            Chunk(
                chunk_no=i,
                content=p,
                doc_type=doc_type,
                chunk_type="text",
                metadata={"source": source},
            )
            for i, p in enumerate(parts)
        ]
