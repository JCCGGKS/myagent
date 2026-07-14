from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from app.business.rag.chunking.base import BaseChunkingStrategy
from app.business.rag.chunking.models import Chunk


class ExcelCsvChunkingStrategy(BaseChunkingStrategy):
    """Excel / CSV 分块（近期）：行级 + 重建表头上下文（05.3 §5）。

    - 每个数据行 → 一块，重建为 ``列名=值`` 让孤立行语义自洽；
    - 另产一个**表概要块**（完整表头 + 行数），负责「找表」，与行块互补；
    - 每块带 ``table_id`` / ``caption`` / ``header`` / ``row_index``；
    - parser 层（openpyxl / pandas）在 近期 把 .xlsx 抽成文本后交本策略，
      跨页问题由 parser 缝合，策略只吃已缝合好的逻辑表。
    """

    def chunk(
        self,
        text: str,
        *,
        doc_type: str = "unknown",
        source: str = "",
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        min_chunk_size: int = 50,
        table_id: str | None = None,
        caption: str | None = None,
        **kwargs: Any,
    ) -> list[Chunk]:
        meta = self._try_json(source) or {}
        table_id = table_id or meta.get("table_id") or (Path(source).stem if source else "table")
        caption = caption or meta.get("caption") or source

        rows = list(csv.reader(io.StringIO(text.strip())))
        rows = [r for r in rows if any(c.strip() for c in r)]
        if not rows:
            return []

        header = [h.strip() for h in rows[0]]
        data = rows[1:]

        chunks: list[Chunk] = []
        no = 0

        # 表概要块：负责「找表」
        summary = f"表格 {table_id}：共 {len(data)} 行，列：{'、'.join(header)}"
        if caption:
            summary = f"{caption}｜{summary}"
        chunks.append(
            Chunk(
                chunk_no=no,
                content=summary,
                doc_type=doc_type,
                chunk_type="table",
                metadata={
                    "source": source,
                    "table_id": table_id,
                    "caption": caption,
                    "header": header,
                    "row_index": -1,
                },
            )
        )
        no += 1

        # 行级块：列名=值（语义自洽）
        for i, row in enumerate(data):
            cells = {header[j]: (row[j].strip() if j < len(row) else "") for j in range(len(header))}
            content = "｜".join(f"{h}={cells[h]}" for h in header)
            chunks.append(
                Chunk(
                    chunk_no=no,
                    content=content,
                    doc_type=doc_type,
                    chunk_type="table",
                    metadata={
                        "source": source,
                        "table_id": table_id,
                        "caption": caption,
                        "header": header,
                        "row_index": i,
                    },
                )
            )
            no += 1
        return chunks

    @staticmethod
    def _try_json(source: str) -> dict[str, Any] | None:
        if not source:
            return None
        try:
            data = json.loads(source)
        except (json.JSONDecodeError, ValueError):
            return None
        return data if isinstance(data, dict) else None
