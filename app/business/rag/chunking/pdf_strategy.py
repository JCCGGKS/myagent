from __future__ import annotations

import re
from typing import Any

from app.business.rag.chunking.base import BaseChunkingStrategy
from app.business.rag.chunking.excel_csv_strategy import ExcelCsvChunkingStrategy
from app.business.rag.chunking.models import Chunk

# 条款起始标记：第X条 / （一） / 1. / A. 等，用于长文档条款级切块。
_CLAUSE_RE = re.compile(
    r"(?:^|\n)\s*(?:第[一二三四五六七八九十百千0-9]+条"
    r"|（?[一二三四五六七八九十]+）?"
    r"|[0-9]+(?:\.[0-9]+)*\.?|[A-Za-z]\.)\s*"
)


class PdfChunkingStrategy(BaseChunkingStrategy):
    """PDF 分块（近期）：含表格 → 行级（同 Excel）；长文档/合同 → 条款级。

    - 表格块：检测到表格式文本（含制表符 / 逗号对齐）时委托 ``ExcelCsvChunkingStrategy``
      做行级 + 表头上下文，chunk_type=table；
    - 长文档 / 合同：按条款标记（第X条 / （一） / 1.）切成 chunk_type=clause 的块；
    - 跨页：parser 先缝合为带 ``page_range`` / ``table_id`` 的逻辑 Table/版式块，
      策略不处理跨页（05.3 §1）。
    """

    def __init__(self) -> None:
        self._table_strategy = ExcelCsvChunkingStrategy()

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
        if self._looks_tabular(text):
            return self._table_strategy.chunk(
                text,
                doc_type=doc_type,
                source=source,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                min_chunk_size=min_chunk_size,
                **kwargs,
            )
        return self._clause_chunks(text, doc_type, source)

    def _looks_tabular(self, text: str) -> bool:
        if "\t" in text:
            return True
        lines = [ln for ln in text.split("\n") if ln.strip()]
        if len(lines) >= 2 and sum(1 for ln in lines if "," in ln) >= max(2, len(lines) // 2):
            return True
        return False

    def _clause_chunks(self, text: str, doc_type: str, source: str) -> list[Chunk]:
        boundaries = [m.start() for m in _CLAUSE_RE.finditer(text)]
        if not boundaries:
            # 无明显条款标记：整段作为一块（不会更长时）
            return [
                Chunk(
                    chunk_no=0,
                    content=text.strip(),
                    doc_type=doc_type,
                    chunk_type="clause",
                    metadata={"source": source},
                )
            ] if text.strip() else []

        if boundaries[0] != 0:
            boundaries = [0, *boundaries]

        chunks: list[Chunk] = []
        no = 0
        for start, end in zip(boundaries, [*boundaries[1:], len(text)]):
            content = text[start:end].strip()
            if not content:
                continue
            chunks.append(
                Chunk(
                    chunk_no=no,
                    content=content,
                    doc_type=doc_type,
                    chunk_type="clause",
                    metadata={"source": source},
                )
            )
            no += 1
        return chunks
