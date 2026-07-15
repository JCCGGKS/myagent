"""测试分块策略模式（chunking 策略）。

覆盖：6 个策略（markdown/word/json/excel·csv/pdf/ppt）+ 注册工厂兜底 + Chunk.chunk_type 序列化。
行为对齐改造前的 chunker（Markdown/JSON/纯文本无回归），并验证
表格 / 条款 / 版式 的近期能力接口与 plans/chunking-strategy-plan.md §4 一致。
"""

import json

import pytest

from app.business.rag.chunking.models import Chunk
from app.business.rag.chunking.registry import get_chunking_strategy
from app.business.rag.chunking.markdown_strategy import MarkdownChunkingStrategy
from app.business.rag.chunking.json_strategy import JsonChunkingStrategy
from app.business.rag.chunking.excel_csv_strategy import ExcelCsvChunkingStrategy
from app.business.rag.chunking.pdf_strategy import PdfChunkingStrategy
from app.business.rag.chunking.ppt_strategy import PptChunkingStrategy
from app.business.rag.chunking.word_strategy import WordChunkingStrategy
from app.business.rag.chunking.recursive_splitter import DefaultTextStrategy


# --------------------------------------------------------------------------- #
# Chunk 模型
# --------------------------------------------------------------------------- #
class TestChunkModel:
    def test_default_chunk_type_is_text(self):
        c = Chunk(chunk_no=0, content="x")
        assert c.chunk_type == "text"

    def test_to_dict_includes_chunk_type(self):
        c = Chunk(chunk_no=1, content="c", doc_type="faq", chunk_type="table")
        d = c.to_dict()
        assert d["chunk_type"] == "table"
        assert d["doc_type"] == "faq"
        assert set(d.keys()) >= {"chunk_no", "content", "heading_path", "doc_type", "chunk_type", "metadata"}


# --------------------------------------------------------------------------- #
# Markdown（当前能力）
# --------------------------------------------------------------------------- #
class TestMarkdownStrategy:
    def test_heading_path_inherited(self):
        text = "# 退款政策\n## 退款条件\n需要满足以下条件。\n## 不支持的情况\n虚拟商品不支持。"
        chunks = MarkdownChunkingStrategy().chunk(text, doc_type="policy", source="p.md")
        assert len(chunks) >= 2
        assert chunks[0].heading_path == ["退款政策", "退款条件"]
        assert chunks[1].heading_path == ["退款政策", "不支持的情况"]
        assert all(c.chunk_type == "text" for c in chunks)

    def test_long_block_degrades_via_splitter(self):
        # 单个标题下超长正文应被递归字符切块降级为多个子块，且继承 heading_path
        long_body = "。".join(f"条款内容编号{i}的说明文字" for i in range(200))
        text = f"# 合同\n## 长条款\n{long_body}"
        chunks = MarkdownChunkingStrategy().chunk(text, doc_type="clause", source="c.md", chunk_size=200)
        assert len(chunks) > 1
        assert all(c.heading_path == ["合同", "长条款"] for c in chunks)


class TestMarkdownQaWithinHeading:
    def test_qa_pairs_under_heading_split_by_pair(self):
        # 标题下的 Q/A 问答对：每对一块，且带上所属标题路径
        text = (
            "# 帮助中心\n"
            "## 退货政策\n"
            "Q: 多久发货？\nA: 一般 48 小时内发货。\n"
            "Q: 支持七天无理由吗？\nA: 支持，自签收起 7 日内。"
        )
        chunks = MarkdownChunkingStrategy().chunk(text, doc_type="faq", source="faq.md")
        qa_chunks = [c for c in chunks if c.content.startswith("问题：")]
        assert len(qa_chunks) == 2
        assert qa_chunks[0].content == "问题：多久发货？\n回答：一般 48 小时内发货。"
        assert qa_chunks[1].content == "问题：支持七天无理由吗？\n回答：支持，自签收起 7 日内。"
        assert all(c.heading_path == ["帮助中心", "退货政策"] for c in qa_chunks)

    def test_no_qa_falls_back_to_recursive(self):
        # 无问答对的普通正文：按原递归字符方式切，不出现「问题：」前缀
        text = "# 说明\n## 概述\n这是一段普通说明文字，没有问答对，应当走递归字符切分兜底。"
        chunks = MarkdownChunkingStrategy().chunk(text, doc_type="policy", source="p.md")
        assert chunks
        assert all(not c.content.startswith("问题：") for c in chunks)
        assert all(c.heading_path == ["说明", "概述"] for c in chunks)

    def test_mixed_block_keeps_prose_and_qa(self):
        # 标题块内同时有正文与问答对：问答对各自成块，正文仍递归切，内容不丢
        text = (
            "## 配送说明\n"
            "下单前请确认收货地址。\n"
            "Q: 多久发货？\nA: 48 小时内。"
        )
        chunks = MarkdownChunkingStrategy().chunk(text, doc_type="faq", source="ship.md")
        qa = [c for c in chunks if c.content.startswith("问题：")]
        prose = [c for c in chunks if not c.content.startswith("问题：")]
        assert len(qa) == 1
        assert qa[0].content == "问题：多久发货？\n回答：48 小时内。"
        assert prose  # 问答对前的中文正文仍被保留并递归切块
        # 标题路径一致
        assert all(c.heading_path == ["配送说明"] for c in chunks)
        # 内容拼接能覆盖原始正文（不丢字）
        joined = "".join(c.content for c in chunks)
        assert "确认收货地址" in joined


# --------------------------------------------------------------------------- #
# JSON（当前能力）
# --------------------------------------------------------------------------- #
class TestJsonStrategy:
    def test_generic_record_chunked(self):
        # 通用 JSON 记录（非 FAQ）：content 切块，source 透传元数据
        text = "这是一条工单样本记录的正文内容。"
        source = json.dumps({" ticket_id": "T1", "status": "closed"}, ensure_ascii=False)
        chunks = JsonChunkingStrategy().chunk(text, doc_type="ticket", source=source)
        assert len(chunks) == 1
        assert chunks[0].content == text
        assert chunks[0].metadata["source"] == source
        assert chunks[0].chunk_type == "text"


# --------------------------------------------------------------------------- #
# Excel / CSV（近期）
# --------------------------------------------------------------------------- #
class TestExcelCsvStrategy:
    def test_row_level_with_header_context(self):
        csv_text = "型号,价格,库存\nA100,999,10\nA200,1999,5"
        chunks = ExcelCsvChunkingStrategy().chunk(csv_text, doc_type="product", source="sku.csv")
        # 1 表概要块 + 2 行级块
        assert len(chunks) == 3
        summary, r1, r2 = chunks
        assert summary.chunk_type == "table"
        assert "共 2 行" in summary.content
        assert r1.chunk_type == "table"
        assert "型号=A100" in r1.content and "价格=999" in r1.content
        assert r1.metadata["row_index"] == 0
        assert r1.metadata["table_id"]
        assert r2.metadata["row_index"] == 1


# --------------------------------------------------------------------------- #
# PDF（近期）
# --------------------------------------------------------------------------- #
class TestPdfStrategy:
    def test_clause_level_for_long_doc(self):
        text = "第一条 本服务条款适用于所有用户。\n第二条 用户应妥善保管账户信息。\n第三条 违规将被封禁。"
        chunks = PdfChunkingStrategy().chunk(text, doc_type="policy", source="agreement.pdf")
        assert len(chunks) == 3
        assert all(c.chunk_type == "clause" for c in chunks)
        assert "第一条" in chunks[0].content

    def test_table_detected_routes_to_row_level(self):
        # 含制表符的表格式文本 → 行级（chunk_type=table）
        table_text = "名称\t价格\n机器人Pro\t1999\n知识库包\t399"
        chunks = PdfChunkingStrategy().chunk(table_text, doc_type="product", source="price.pdf")
        assert any(c.chunk_type == "table" for c in chunks)


# --------------------------------------------------------------------------- #
# PPT（近期）
# --------------------------------------------------------------------------- #
class TestPptStrategy:
    def test_slide_separated(self):
        text = "封面：产品介绍\n---\n第一页：功能亮点\n- 并发\n- 稳定\n---\n第二页：价格"
        chunks = PptChunkingStrategy().chunk(text, doc_type="product", source="deck.ppt")
        assert len(chunks) == 3
        assert chunks[1].chunk_type == "clause"  # 含要点标记（'-'）
        assert chunks[0].chunk_type == "text"

    def test_paragraph_fallback(self):
        text = "段落一内容\n\n段落二内容"
        chunks = PptChunkingStrategy().chunk(text, doc_type="product", source="deck.ppt")
        assert len(chunks) == 2


# --------------------------------------------------------------------------- #
# Word（近期，复用结构切块）
# --------------------------------------------------------------------------- #
class TestWordStrategy:
    def test_reuses_structure_chunk(self):
        text = "# 服务协议\n## 第一条 定义\n本协议指……"
        chunks = WordChunkingStrategy().chunk(text, doc_type="policy", source="agreement.docx")
        assert chunks[0].heading_path == ["服务协议", "第一条 定义"]
        assert chunks[0].chunk_type == "text"


# --------------------------------------------------------------------------- #
# 注册工厂兜底
# --------------------------------------------------------------------------- #
class TestRegistry:
    def test_unknown_format_falls_back_to_default(self):
        strat = get_chunking_strategy("unknown", "xyz")
        assert isinstance(strat, DefaultTextStrategy)

    def test_format_dispatch(self):
        assert isinstance(get_chunking_strategy("unknown", "markdown"), MarkdownChunkingStrategy)
        assert isinstance(get_chunking_strategy("unknown", "json"), JsonChunkingStrategy)
        assert isinstance(get_chunking_strategy("unknown", "word"), WordChunkingStrategy)
        assert isinstance(get_chunking_strategy("unknown", "excel"), ExcelCsvChunkingStrategy)
        assert isinstance(get_chunking_strategy("unknown", "csv"), ExcelCsvChunkingStrategy)
        assert isinstance(get_chunking_strategy("unknown", "pdf"), PdfChunkingStrategy)
        assert isinstance(get_chunking_strategy("unknown", "ppt"), PptChunkingStrategy)

    def test_default_text_strategy_recursive_split(self):
        text = "。".join(f"句子{i}内容" for i in range(100))
        chunks = DefaultTextStrategy().chunk(text, chunk_size=200)
        assert len(chunks) > 1
        assert all(c.chunk_type == "text" for c in chunks)
