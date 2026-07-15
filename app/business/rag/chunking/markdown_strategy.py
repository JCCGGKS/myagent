from __future__ import annotations

import re
from typing import Any

from app.business.rag.chunking.base import BaseChunkingStrategy
from app.business.rag.chunking.models import Chunk
from app.business.rag.chunking.recursive_splitter import RecursiveSplitter
from app.business.rag.chunking.structure_chunk import _parse_heading_blocks

# 问答对标记：Q:/问： 开头为问题，A:/答： 开头为答案（中文或英文标记均可）
_QA_RE = re.compile(r"^\s*(?:Q|问)\s*[:：]?\s*(.*)$")
_A_RE = re.compile(r"^\s*(?:A|答)\s*[:：]?\s*(.*)$")


class MarkdownChunkingStrategy(BaseChunkingStrategy):
    """Markdown 分块：先按标题结构切分；标题块内若含问答对则按问答对切，
    否则按原递归字符方式切（与改造前 chunker 行为一致）。

    即「结构为主、问答优先、字符兜底」：
    - 先 ``_parse_heading_blocks`` 拆成带 heading_path 的标题块；
    - 每个标题块内：检测到 ``Q:/问：`` 形式的问答对 → 每对一块（问题+答案自包含）；
      块内其余非问答正文 → 仍按 RecursiveSplitter 递归字符切，不丢内容；
    - 整块无问答对 → 整块走递归字符切（继承 heading_path）。
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
        blocks = _parse_heading_blocks(text)
        chunks: list[Chunk] = []
        no = 0
        for heading_path, content in blocks:
            for piece in self._chunk_block(
                content,
                heading_path,
                doc_type,
                source,
                chunk_size,
                chunk_overlap,
                min_chunk_size,
            ):
                piece.chunk_no = no
                chunks.append(piece)
                no += 1
        return chunks

    def _chunk_block(
        self,
        content: str,
        heading_path: list[str],
        doc_type: str,
        source: str,
        chunk_size: int,
        chunk_overlap: int,
        min_chunk_size: int,
    ) -> list[Chunk]:
        """单标题块内：问答对逐对切块，非问答正文递归字符切。"""
        if not content:
            return []
        segments = _segment_markdown_block(content)
        out: list[Chunk] = []
        for kind, payload in segments:
            if kind == "qa":
                q, a = payload
                out.append(
                    Chunk(
                        chunk_no=0,
                        content=f"问题：{q}\n回答：{a}",
                        heading_path=heading_path,
                        doc_type=doc_type,
                        chunk_type="text",
                        metadata={"source": source, "heading_path": heading_path},
                    )
                )
            else:
                for part in self._splitter.split(
                    payload, chunk_size, chunk_overlap, min_chunk_size
                ):
                    out.append(
                        Chunk(
                            chunk_no=0,
                            content=part,
                            heading_path=heading_path,
                            doc_type=doc_type,
                            chunk_type="text",
                            metadata={"source": source, "heading_path": heading_path},
                        )
                    )
        return out


def _segment_markdown_block(text: str) -> list[tuple[str, Any]]:
    """把标题块正文切成段：``("qa", (question, answer))`` 或 ``("prose", text)``。

    逐行扫描：``Q:/问：`` 起新问答；``A:/答：``（且已在问答上下文中）收答案；
    其余行：在问答上下文中视为答案续行，否则归入 prose。问答对与 prose 都被保留，
    交由上层分别按问答 / 递归字符方式切块。
    """
    segments: list[tuple[str, Any]] = []
    cur_q: str | None = None
    ans_buf: list[str] = []
    prose_buf: list[str] = []

    def _flush_prose() -> None:
        if prose_buf:
            segments.append(("prose", "\n".join(prose_buf).strip()))
            prose_buf.clear()

    def _flush_qa() -> None:
        nonlocal cur_q
        if cur_q is not None:
            segments.append(("qa", (cur_q, "\n".join(ans_buf).strip())))
            cur_q = None

    for line in text.splitlines():
        qm = _QA_RE.match(line)
        am = _A_RE.match(line)
        if qm:
            _flush_prose()
            _flush_qa()
            cur_q = qm.group(1).strip()
            ans_buf = []
        elif am and cur_q is not None:
            ans_buf.append(am.group(1).strip())
        else:
            if cur_q is not None:
                ans_buf.append(line.strip())  # 答案续行
            else:
                prose_buf.append(line)
    _flush_prose()
    _flush_qa()
    return segments
