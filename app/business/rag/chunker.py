from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("rag")


@dataclass
class Chunk:
    """一个切块结果。"""

    chunk_no: int
    content: str
    # 结构切块时记录的层级信息
    heading_path: list[str] = field(default_factory=list)  # 例如 ["退款政策", "退款条件"]
    doc_type: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_no": self.chunk_no,
            "content": self.content,
            "heading_path": self.heading_path,
            "doc_type": self.doc_type,
            "metadata": self.metadata,
        }


class Chunker:
    """文档切块器：优先按 Markdown 结构切块，长块用递归字符切块兜底。"""

    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        min_chunk_size: int = 50,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        # 递归字符分块用的分隔符优先级：段落 > 换行 > 句子 > 空格
        self._separators = ["\n\n", "\n", "。", "；", "，", " ", ""]

    def chunk_markdown(
        self,
        text: str,
        doc_type: str = "unknown",
        source: str = "",
        max_chunk_chars: int | None = None,
    ) -> list[Chunk]:
        """按 Markdown 标题结构切块。

        规则：
        1. 以 `#`~`######` 标题为边界切分逻辑块
        2. 每个逻辑块继承其上层标题路径（heading_path）
        3. 若某个逻辑块超过 max_chunk_chars，用递归字符切块继续切
        """
        max_chars = max_chunk_chars or self.chunk_size
        lines = text.split("\n")
        blocks: list[tuple[list[str], str]] = []  # (heading_path, content)
        current_headings: list[str] = []
        current_lines: list[str] = []

        heading_re = re.compile(r"^(#{1,6})\s+(.*)$")

        def _flush() -> None:
            if current_lines:
                blocks.append((list(current_headings), "\n".join(current_lines).strip()))
                current_lines.clear()

        for line in lines:
            m = heading_re.match(line)
            if m:
                _flush()
                level = len(m.group(1))
                title = m.group(2).strip()
                # 维护 heading 栈：层级深的覆盖同层
                current_headings = current_headings[: level - 1]
                current_headings.append(title)
            else:
                current_lines.append(line)

        _flush()

        chunks: list[Chunk] = []
        no = 0
        for heading_path, content in blocks:
            if not content:
                continue
            if len(content) <= max_chars:
                chunks.append(
                    Chunk(
                        chunk_no=no,
                        content=content,
                        heading_path=heading_path,
                        doc_type=doc_type,
                        metadata={"source": source, "heading_path": heading_path},
                    )
                )
                no += 1
            else:
                # 长块用递归字符切块继续切
                sub_parts = self._recursive_split(content)
                for part in sub_parts:
                    chunks.append(
                        Chunk(
                            chunk_no=no,
                            content=part,
                            heading_path=heading_path,
                            doc_type=doc_type,
                            metadata={"source": source, "heading_path": heading_path},
                        )
                    )
                    no += 1
        logger.info(_tagged("rag", "chunk_markdown done doc_type=%s blocks=%d chunks=%d"), doc_type, len(blocks), len(chunks))
        return chunks

    def chunk_text(
        self,
        text: str,
        doc_type: str = "unknown",
        source: str = "",
    ) -> list[Chunk]:
        """通用文本切块（无 Markdown 结构时）。"""
        parts = self._recursive_split(text)
        chunks: list[Chunk] = []
        for i, part in enumerate(parts):
            chunks.append(
                Chunk(
                    chunk_no=i,
                    content=part,
                    heading_path=[],
                    doc_type=doc_type,
                    metadata={"source": source},
                )
            )
        logger.info(_tagged("rag", "chunk_text done doc_type=%s chunks=%d"), doc_type, len(chunks))
        return chunks

    def _recursive_split(self, text: str) -> list[str]:
        """递归字符切块：按分隔符优先级切，直到每块 <= chunk_size。"""

        def _split(segment: str, sep_index: int) -> list[str]:
            if len(segment) <= self.chunk_size or sep_index >= len(self._separators):
                return [segment]

            sep = self._separators[sep_index]
            if sep == "":
                # 最后兜底：硬切
                return self._hard_split(segment)

            pieces = segment.split(sep)
            if len(pieces) <= 1:
                # 该分隔符切不开，换下一个
                return _split(segment, sep_index + 1)

            # 用分隔符重新拼接，保持重叠
            merged: list[str] = []
            buf = ""
            for piece in pieces:
                candidate = buf + (sep if buf else "") + piece
                if len(candidate) <= self.chunk_size:
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
                if len(m) <= self.chunk_size:
                    result.append(m.strip())
                else:
                    result.extend(_split(m, sep_index + 1))
            return [r for r in result if r]

        return _split(text.strip(), 0)

    def _hard_split(self, text: str) -> list[str]:
        """硬切：按 chunk_size 直接截断，保留 overlap。"""
        if len(text) <= self.chunk_size:
            return [text.strip()] if text.strip() else []
        parts: list[str] = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            part = text[start:end].strip()
            if part and len(part) >= self.min_chunk_size:
                parts.append(part)
            start = end - self.chunk_overlap
        return parts
