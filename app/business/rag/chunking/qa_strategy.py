from __future__ import annotations

import json
import re
from typing import Any

from app.business.rag.chunking.base import BaseChunkingStrategy
from app.business.rag.chunking.models import Chunk
from app.business.rag.chunking.recursive_splitter import RecursiveSplitter
from app.business.rag.chunking.structure_chunk import chunk_markdown_text

# 问答配对识别：Q:/问： 起头为问题，A:/答： 起头为回答（同行或下一行均可）。
_QA_RE = re.compile(r"^\s*(?:Q|问)\s*[:：]?\s*(.*)$")
_A_RE = re.compile(r"^\s*(?:A|答)\s*[:：]?\s*(.*)$")


def _split_qa_markdown(text: str) -> list[tuple[str, str]]:
    """把含 ``Q:/问：`` 的 Markdown 文档拆成 [(question, answer), ...]。"""
    pairs: list[tuple[str, str]] = []
    cur_q: str | None = None
    cur_a: list[str] = []
    for line in text.split("\n"):
        m = _QA_RE.match(line)
        if m:
            if cur_q is not None:
                pairs.append((cur_q, "\n".join(cur_a).strip()))
            cur_q = m.group(1).strip()
            cur_a = []
        elif cur_q is not None:
            am = _A_RE.match(line)
            cur_a.append((am.group(1) if am else line).strip())
    if cur_q is not None:
        pairs.append((cur_q, "\n".join(cur_a).strip()))
    return [(q, a) for q, a in pairs if q and a]


class QaChunkingStrategy(BaseChunkingStrategy):
    """FAQ 分块（当前能力）：每对一块，按 ``doc_type=faq`` 命中，与文件格式无关。

    - JSON FAQ：``source`` 里带 ``question``（ingestion 透传），``text`` 即 answer
      → 拼成 ``问题：{question}\\n回答：{text}`` 一块；
    - Markdown Q&A：正文含 ``Q:/问：`` 配对 → 每对一块；
    - 兜底：非 Q&A 的普通 FAQ 文档（如标题层级 Markdown）按结构切块，保留 heading_path，
      避免退化成纯递归切（对齐原 chunk_markdown 行为，order_faq.md 等无回归）。
    """

    def __init__(self, splitter: RecursiveSplitter | None = None) -> None:
        self._splitter = splitter or RecursiveSplitter()

    def chunk(
        self,
        text: str,
        *,
        doc_type: str = "faq",
        source: str = "",
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        min_chunk_size: int = 50,
        **kwargs: Any,
    ) -> list[Chunk]:
        # 1) JSON FAQ 单记录：question 在 source 元数据，text 即 answer
        meta = self._try_json(source)
        question = (meta or {}).get("question") or (meta or {}).get("q")
        if question and text:
            combined = f"问题：{question}\n回答：{text}"
            return self._emit([combined], doc_type, source, chunk_size, chunk_overlap, min_chunk_size)

        # 2) Markdown Q&A 文档：Q:/问： 配对 → 每对一块
        pairs = _split_qa_markdown(text)
        if pairs:
            combined = [f"问题：{q}\n回答：{a}" for q, a in pairs]
            return self._emit(combined, doc_type, source, chunk_size, chunk_overlap, min_chunk_size)

        # 3) 兜底：按标题结构切块（保留 heading_path）
        return chunk_markdown_text(
            text,
            doc_type=doc_type,
            source=source,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            splitter=self._splitter,
            min_chunk_size=min_chunk_size,
        )

    def _emit(
        self,
        combined_texts: list[str],
        doc_type: str,
        source: str,
        chunk_size: int,
        chunk_overlap: int,
        min_chunk_size: int,
    ) -> list[Chunk]:
        """每个 QA 组合文本成一块；超长再降级为递归字符切。"""
        chunks: list[Chunk] = []
        no = 0
        for combined in combined_texts:
            if not combined.strip():
                continue
            if len(combined) <= chunk_size:
                chunks.append(
                    Chunk(
                        chunk_no=no,
                        content=combined,
                        doc_type=doc_type,
                        chunk_type="text",
                        metadata={"source": source},
                    )
                )
                no += 1
            else:
                for part in self._splitter.split(combined, chunk_size, chunk_overlap, min_chunk_size):
                    chunks.append(
                        Chunk(
                            chunk_no=no,
                            content=part,
                            doc_type=doc_type,
                            chunk_type="text",
                            metadata={"source": source},
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
