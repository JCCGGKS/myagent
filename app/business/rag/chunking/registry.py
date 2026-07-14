from __future__ import annotations

from app.business.rag.chunking.base import BaseChunkingStrategy
from app.business.rag.chunking.recursive_splitter import DefaultTextStrategy
from app.business.rag.chunking.markdown_strategy import MarkdownChunkingStrategy
from app.business.rag.chunking.word_strategy import WordChunkingStrategy
from app.business.rag.chunking.json_strategy import JsonChunkingStrategy
from app.business.rag.chunking.qa_strategy import QaChunkingStrategy  # FAQ：JSON / Markdown Q&A 均每对一块
from app.business.rag.chunking.excel_csv_strategy import ExcelCsvChunkingStrategy  # 近期
from app.business.rag.chunking.pdf_strategy import PdfChunkingStrategy  # 近期
from app.business.rag.chunking.ppt_strategy import PptChunkingStrategy  # 近期

# 单点注册（与 tool.TOOLS 同思路）：新增 = 加一行 + 新建对应策略文件。
# 内容类型（doc_type）优先于文件格式（doc_format）：FAQ 无论 JSON 还是 Markdown Q&A
# 都走每对一块（05.3 §3）。
DOC_TYPE_STRATEGIES: dict[str, type[BaseChunkingStrategy]] = {
    "faq": QaChunkingStrategy,
}

FORMAT_STRATEGIES: dict[str, type[BaseChunkingStrategy]] = {
    "markdown": MarkdownChunkingStrategy,
    "word": WordChunkingStrategy,
    "json": JsonChunkingStrategy,  # 通用 JSON 记录（非 FAQ，如工单样本）
    "excel": ExcelCsvChunkingStrategy,
    "csv": ExcelCsvChunkingStrategy,
    "pdf": PdfChunkingStrategy,
    "ppt": PptChunkingStrategy,
}


def get_chunking_strategy(
    doc_type: str, doc_format: str
) -> BaseChunkingStrategy:
    """按 doc_type / doc_format 选分块策略（工厂）。

    - doc_type 命中优先（如 faq → QaChunkingStrategy）；
    - 否则按 doc_format 命中；
    - 都未命中 → DefaultTextStrategy（递归字符全量切兜底）。
    """
    if doc_type in DOC_TYPE_STRATEGIES:
        return DOC_TYPE_STRATEGIES[doc_type]()
    return FORMAT_STRATEGIES.get(doc_format, DefaultTextStrategy)()
