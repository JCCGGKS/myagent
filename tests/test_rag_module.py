"""测试 RAG 模块（工具化改造后）。"""

import pytest
from unittest.mock import MagicMock, patch

from app.rag import RagRetrieveTool, BM25Strategy, SemanticStrategy, HybridStrategy
from app.rag.qdrant_client import QdrantClient


class TestQdrantClient:
    """测试 QdrantClient（模拟实现）。"""

    def test_search_bm25_should_return_results(self):
        """测试 BM25 检索返回结果。"""
        client = QdrantClient()
        results = client.search_bm25(query="测试查询", limit=5)
        assert isinstance(results, list)
        assert len(results) > 0
        assert "id" in results[0]
        assert "content" in results[0]

    def test_search_semantic_should_return_results(self):
        """测试语义向量检索返回结果。"""
        client = QdrantClient()
        results = client.search_semantic(query_vector=[0.1, 0.2, 0.3], limit=5)
        assert isinstance(results, list)
        assert len(results) > 0


class TestRetrievalStrategy:
    """测试检索策略。"""

    def setup_method(self):
        from app.rag.qdrant_client import QdrantClient

        self.client = QdrantClient()
        self.bm25_strategy = BM25Strategy(client=self.client, min_score_threshold=0.0)
        self.semantic_strategy = SemanticStrategy(
            client=self.client,
            embedding_client=None,  # 模拟实现，不需要真实 embedding 客户端
            min_score_threshold=0.0,
        )
        self.hybrid_strategy = HybridStrategy(
            bm25_strategy=self.bm25_strategy,
            semantic_strategy=self.semantic_strategy,
            fusion_method="rrf",
        )

    def test_bm25_strategy_should_retrieve(self):
        """测试 BM25 策略能够检索。"""
        docs = self.bm25_strategy.retrieve(query="测试查询")
        assert isinstance(docs, list)

    def test_semantic_strategy_should_retrieve(self):
        """测试语义策略能够检索。"""
        docs = self.semantic_strategy.retrieve(query="测试查询")
        assert isinstance(docs, list)

    def test_hybrid_strategy_should_retrieve(self):
        """测试混合策略能够检索。"""
        docs = self.hybrid_strategy.retrieve(query="测试查询")
        assert isinstance(docs, list)


class TestRagRetrieveTool:
    """测试 RAG 检索工具。"""

    def test_run_should_return_documents(self):
        """测试工具调用返回文档列表。"""
        tool = RagRetrieveTool()
        results = tool.run(query="测试查询")
        assert isinstance(results, list)
        if results:
            assert "content" in results[0]
            assert "metadata" in results[0]

    def test_name_should_be_rag_retrieve(self):
        """测试工具名称为 rag_retrieve。"""
        tool = RagRetrieveTool()
        assert tool.name == "rag_retrieve"

    def test_description_should_not_be_empty(self):
        """测试工具描述不为空。"""
        tool = RagRetrieveTool()
        assert tool.description != ""

    def test_to_tool_schema_should_return_valid_schema(self):
        """测试工具 schema 符合 OpenAI tools 格式。"""
        tool = RagRetrieveTool()
        schema = tool.to_tool_schema()
        assert "type" in schema
        assert "function" in schema
        assert "name" in schema["function"]
        assert "parameters" in schema["function"]
