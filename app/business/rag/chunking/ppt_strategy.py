from __future__ import annotations

import re
from typing import Any

from app.business.rag.chunking.base import BaseChunkingStrategy
from app.business.rag.chunking.models import Chunk

# 幻灯片分隔符（parser 层把每页用 --- 隔开），无则用空行分段。
_SLIDE_SEP_RE = re.compile(r"\n\s*---\s*\n")
# 版式区块中疑似条款/要点的标记（编号 / 中文序号 / 项目符号）。
_POINT_RE = re.compile(r"(?:^|\n)\s*(?:（?[一二三四五六七八九十]+）?|[0-9]+(?:\.[0-9]+)*\.?|[-•·*])\s*")


class PptChunkingStrategy(BaseChunkingStrategy):
    """PPT 分块（近期）：按版式分栏/段落切块（05.3 §3）。

    - parser 层把每页抽成纯文本并按阅读序用 ``---`` 分隔；
    - 逐页（或逐空行段落）切成 chunk_type=text 的块；
    - 页内若出现条款/要点标记（（一）/1./•）则升级为 chunk_type=clause；
    - 跨页版式块由 parser 按阅读序缝合，策略不处理跨页。
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
        **kwargs: Any,
    ) -> list[Chunk]:
        if _SLIDE_SEP_RE.search(text):
            blocks = [b for b in _SLIDE_SEP_RE.split(text) if b.strip()]
        else:
            blocks = [b for b in text.split("\n\n") if b.strip()]

        chunks: list[Chunk] = []
        no = 0
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            chunk_type = "clause" if _POINT_RE.search(block) else "text"
            chunks.append(
                Chunk(
                    chunk_no=no,
                    content=block,
                    doc_type=doc_type,
                    chunk_type=chunk_type,
                    metadata={"source": source},
                )
            )
            no += 1
        return chunks
