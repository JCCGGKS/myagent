from __future__ import annotations

from app.business.rag.chunking.base import BaseChunkingStrategy
from app.business.rag.chunking.models import Chunk

# 递归字符切分的分隔符优先级：段落 > 换行 > 句子 > 分号 > 逗号 > 空格 > 硬切。
# 与 chunker.py 一致，保证改造前后纯文本切块行为不变。
_SEPARATORS = ["\n\n", "\n", "。", "；", "，", " ", ""]


class RecursiveSplitter:
    """共享递归字符切分：结构切块超长时的兜底（迁移自 chunker._recursive_split / _hard_split）。

    思路（05.3 §1）：结构性文档「结构为主、字符为补」。当某逻辑块超过
    ``chunk_size`` 且标点分隔符都切不开时，兜底用 ``chunk_size + chunk_overlap``
    滑动窗口硬切，保证相邻块边界语义连贯（overlap 仅在此兜底层生效）。
    """

    def __init__(self, separators: list[str] | None = None) -> None:
        self._separators = separators or _SEPARATORS

    def split(
        self,
        text: str,
        chunk_size: int,
        chunk_overlap: int,
        min_chunk_size: int,
    ) -> list[str]:
        """按分隔符优先级逐级切，最后无可切分隔符时按滑窗硬切。"""

        def _hard_split(segment: str) -> list[str]:
            if len(segment) <= chunk_size:
                return [segment.strip()] if segment.strip() else []
            parts: list[str] = []
            start = 0
            while start < len(segment):
                end = start + chunk_size
                part = segment[start:end].strip()
                if part and len(part) >= min_chunk_size:
                    parts.append(part)
                start = end - chunk_overlap
            return parts

        def _split(segment: str, sep_index: int) -> list[str]:
            if len(segment) <= chunk_size or sep_index >= len(self._separators):
                return [segment]
            sep = self._separators[sep_index]
            if sep == "":
                return _hard_split(segment)

            pieces = segment.split(sep)
            if len(pieces) <= 1:
                # 该分隔符切不开，换下一个
                return _split(segment, sep_index + 1)

            # 用分隔符重新拼接，保持块内完整语义
            merged: list[str] = []
            buf = ""
            for piece in pieces:
                candidate = buf + (sep if buf else "") + piece
                if len(candidate) <= chunk_size:
                    buf = candidate
                else:
                    if buf:
                        merged.append(buf)
                    buf = piece
            if buf:
                merged.append(buf)

            # 递归处理仍然超长的块
            result: list[str] = []
            for m in merged:
                if len(m) <= chunk_size:
                    result.append(m.strip())
                else:
                    result.extend(_split(m, sep_index + 1))
            return [r for r in result if r]

        return _split(text.strip(), 0)


class DefaultTextStrategy(BaseChunkingStrategy):
    """未知格式的 catch-all：直接走 RecursiveSplitter 全量切（兜底策略）。"""

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
