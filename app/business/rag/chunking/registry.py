from __future__ import annotations

from app.business.rag.chunking.base import BaseChunkingStrategy
from app.business.rag.chunking.recursive_splitter import DefaultTextStrategy
from app.business.rag.chunking.markdown_strategy import MarkdownChunkingStrategy
from app.business.rag.chunking.word_strategy import WordChunkingStrategy
from app.business.rag.chunking.json_strategy import JsonChunkingStrategy
from app.business.rag.chunking.excel_csv_strategy import ExcelCsvChunkingStrategy
from app.business.rag.chunking.pdf_strategy import PdfChunkingStrategy
from app.business.rag.chunking.ppt_strategy import PptChunkingStrategy

# 单点注册（与 tool.TOOLS 同思路）：新增 = 加一行 + 新建对应策略文件。
# 分块策略完全按文件格式（doc_format）选择；FAQ 等内容类型就是普通的
# JSON / Markdown 文件，无需单独策略（见下 FORMAT_STRATEGIES）。
FORMAT_STRATEGIES: dict[str, type[BaseChunkingStrategy]] = {
    "markdown": MarkdownChunkingStrategy,
    "word": WordChunkingStrategy,
    "json": JsonChunkingStrategy,  # 通用 JSON 记录（含 FAQ：{question,answer} 也按记录切块）
    "excel": ExcelCsvChunkingStrategy,
    "csv": ExcelCsvChunkingStrategy,
    "pdf": PdfChunkingStrategy,
    "ppt": PptChunkingStrategy,
}


def get_chunking_strategy(
    doc_type: str, doc_format: str
) -> BaseChunkingStrategy:
    """按 doc_format 选分块策略（工厂）。

    - doc_format 命中 FORMAT_STRATEGIES 则返回对应策略；
    - 都未命中 → DefaultTextStrategy（递归字符全量切兜底）。

    `doc_type` 为内容类型（如 faq），仅作元信息记录，不参与策略选择：
    FAQ 的 JSON / Markdown 文件分别由 JsonChunkingStrategy / MarkdownChunkingStrategy 处理。
    """
    return FORMAT_STRATEGIES.get(doc_format, DefaultTextStrategy)()
