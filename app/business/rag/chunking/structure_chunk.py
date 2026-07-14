from __future__ import annotations

import re
from typing import Any

from app.business.rag.chunking.models import Chunk
from app.business.rag.chunking.recursive_splitter import RecursiveSplitter
from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("rag")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _parse_heading_blocks(text: str) -> list[tuple[list[str], str]]:
    """解析 Markdown / Word 标题树为逻辑块列表。

    返回 ``[(heading_path, content), ...]``：每个逻辑块继承其上层标题路径
    （heading_path，如 ["退款政策", "退款条件"]），content 为该标题下的正文。
    维护 heading 栈：层级深的覆盖同层（level 决定裁剪深度）。
    """
    blocks: list[tuple[list[str], str]] = []
    current_headings: list[str] = []
    current_lines: list[str] = []

    def _flush() -> None:
        if current_lines:
            blocks.append((list(current_headings), "\n".join(current_lines).strip()))
            current_lines.clear()

    for line in text.split("\n"):
        m = _HEADING_RE.match(line)
        if m:
            _flush()
            level = len(m.group(1))
            title = m.group(2).strip()
            current_headings = current_headings[: level - 1]
            current_headings.append(title)
        else:
            current_lines.append(line)
    _flush()
    return blocks


def structure_chunk(
    blocks: list[tuple[list[str], str]],
    *,
    doc_type: str,
    source: str,
    chunk_size: int,
    chunk_overlap: int,
    splitter: RecursiveSplitter,
    min_chunk_size: int = 50,
) -> list[Chunk]:
    """按 ``(heading_path, content)`` 列表切逻辑块（Markdown / Word 共用）。

    - 每个逻辑块 ≤ chunk_size 直接成 ``Chunk(chunk_type="text")``，继承 heading_path；
    - 超长块交给 ``splitter.split`` 降级（chunk_size + chunk_overlap 滑窗兜底）；
    - 结构块之间**不重叠**，overlap 仅在递归字符兜底层生效（05.3 §1）。
    """
    chunks: list[Chunk] = []
    no = 0
    for heading_path, content in blocks:
        if not content:
            continue
        if len(content) <= chunk_size:
            chunks.append(
                Chunk(
                    chunk_no=no,
                    content=content,
                    heading_path=heading_path,
                    doc_type=doc_type,
                    chunk_type="text",
                    metadata={"source": source, "heading_path": heading_path},
                )
            )
            no += 1
        else:
            sub_parts = splitter.split(content, chunk_size, chunk_overlap, min_chunk_size)
            for part in sub_parts:
                chunks.append(
                    Chunk(
                        chunk_no=no,
                        content=part,
                        heading_path=heading_path,
                        doc_type=doc_type,
                        chunk_type="text",
                        metadata={"source": source, "heading_path": heading_path},
                    )
                )
                no += 1
    logger.info(
        _tagged("rag", "structure_chunk done doc_type=%s blocks=%d chunks=%d"),
        doc_type,
        len(blocks),
        len(chunks),
    )
    return chunks


def chunk_markdown_text(
    text: str,
    *,
    doc_type: str,
    source: str,
    chunk_size: int,
    chunk_overlap: int,
    splitter: RecursiveSplitter,
    min_chunk_size: int = 50,
) -> list[Chunk]:
    """解析标题树并结构切块：Markdown / Word 策略共用的入口。"""
    blocks = _parse_heading_blocks(text)
    return structure_chunk(
        blocks,
        doc_type=doc_type,
        source=source,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        splitter=splitter,
        min_chunk_size=min_chunk_size,
    )
