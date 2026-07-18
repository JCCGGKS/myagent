"""测试 RAG 模块（工具化改造后）。"""

import pytest
from unittest.mock import MagicMock, patch

from app.business.rag import BM25Strategy, SemanticStrategy, HybridStrategy
from app.business.rag.retrieval.models import Document
from app.business.tools.rag_tool import RagRetrieveTool
from app.pkgs.vector import QdrantClient


def _fake_client() -> QdrantClient:
    """构造 QdrantClient 但用假底层客户端，避免依赖真实 Qdrant 服务。"""
    client = QdrantClient.__new__(QdrantClient)
    client.host = "localhost"
    client.port = 6333
    client.collection_name = "test_collection"
    client.api_key = None
    client.vector_size = 4
    client.distance = "Cosine"
    client._collection_ready = True
    client._client = MagicMock()
    return client


class TestQdrantClient:
    """测试 QdrantClient 结果转换（底层客户端 mock）。"""

    def test_search_semantic_should_return_results(self):
        client = _fake_client()
        client._client.query_points.return_value.points = [
            MagicMock(id="2", score=0.9, payload={"content": "语义内容"})
        ]
        results = client.search_semantic(query_vector=[0.1, 0.2, 0.3], limit=5)
        assert isinstance(results, list)
        assert len(results) > 0


class TestRetrievalStrategy:
    """测试检索策略。"""

    def setup_method(self):
        self.client = _fake_client()
        # 手搓 BM25 策略在索引为空时，从 Qdrant 一次性重建（lazy rebuild）。
        # 测试用假 client 不连真实 Qdrant，故把 scroll_all mock 成空召回（安全 no-op），
        # 单个用例再按需改 return_value 喂入数据。同时重置索引导单例避免用例间污染。
        self.client.scroll_all = MagicMock(return_value=[])
        from app.business.rag.retrieval.bm25 import get_bm25_store
        get_bm25_store()._indexes.clear()
        get_bm25_store()._doc_map.clear()
        self.bm25_strategy = BM25Strategy(client=self.client, min_score_threshold=0.0)
        self.semantic_strategy = SemanticStrategy(
            client=self.client,
            embedding_client=MagicMock(**{"embed_one.return_value": [0.1, 0.2, 0.3, 0.4]}),
            min_score_threshold=0.0,
        )
        self.hybrid_strategy = HybridStrategy(
            strategies=[self.bm25_strategy, self.semantic_strategy],
        )

    def test_bm25_strategy_should_retrieve(self):
        # 用 scroll_all 喂入一条命中 query 的数据，rebuild 后内存索引可检索。
        self.client.scroll_all.return_value = [
            {"id": "1", "payload": {"content": "测试查询 c1", "doc_type": "faq"}}
        ]
        docs = self.bm25_strategy.retrieve(query="测试查询")
        assert isinstance(docs, list)
        assert len(docs) > 0

    def test_semantic_strategy_should_retrieve(self):
        self.client._client.query_points.return_value.points = [
            MagicMock(id="2", score=0.8, payload={"content": "c2", "doc_type": "policy"})
        ]
        docs = self.semantic_strategy.retrieve(query="测试查询")
        assert isinstance(docs, list)
        assert len(docs) > 0

    def test_hybrid_strategy_should_retrieve(self):
        self.client._client.query_points.return_value.points = [
            MagicMock(id="3", score=0.7, payload={"content": "c3", "doc_type": "faq"})
        ]
        docs = self.hybrid_strategy.retrieve(query="测试查询")
        assert isinstance(docs, list)


class TestRagRetrieveTool:
    """测试 RAG 检索工具。"""

    def _fake_tool(self) -> RagRetrieveTool:
        from app.business.rag.retrieval.models import Document

        fake_strategy = MagicMock()
        fake_strategy.retrieve.return_value = [
            Document(id="x1", content="测试内容", metadata={"doc_type": "faq"}, score=0.9)
        ]
        return RagRetrieveTool(strategy=fake_strategy)

    def test_run_should_return_documents(self):
        """测试工具调用返回文档列表。"""
        tool = self._fake_tool()
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


class TestRerankClient:
    """测试 DashScope Rerank 客户端（mock HTTP）。"""

    def test_build_disabled_returns_none(self, monkeypatch):
        from app.business.rag.retrieval.rerank import build_rerank_client
        # 无配置 -> 返回 None
        monkeypatch.setattr(
            "app.config.rag_config.load_rag_config_raw",
            lambda: {},
        )
        assert build_rerank_client() is None

    def test_build_missing_model_or_base_url_returns_none(self, monkeypatch):
        from app.business.rag.retrieval.rerank import build_rerank_client
        # 已开启但缺少 model / base_url（改由配置显式提供，不再有代码内默认）
        # -> 视为未就绪，跳过重排返回 None
        monkeypatch.setattr(
            "app.config.rag_config.load_rag_config_raw",
            lambda: {"rerank": {"enabled": True, "api_key": "k", "model": ""}},
        )
        assert build_rerank_client() is None
        monkeypatch.setattr(
            "app.config.rag_config.load_rag_config_raw",
            lambda: {"rerank": {"enabled": True, "api_key": "k", "base_url": ""}},
        )
        assert build_rerank_client() is None

    def test_rerank_reorders_by_score(self, monkeypatch):
        import json
        from app.business.rag.retrieval.rerank import RerankClient

        def fake_post(url, json=None, headers=None, timeout=None):
            class R:
                def raise_for_status(self): pass
                def json(self):
                    return {"results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.3},
                    ]}
            return R()

        monkeypatch.setattr("app.business.rag.retrieval.rerank.requests.post", fake_post)
        client = RerankClient(
            api_key="test-key",
            model="gated-rerank",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        scored = client.rerank("q", ["docA", "docB"])
        assert [i for i, _ in scored] == [1, 0]  # 降序：docB 在前

    def test_rerank_failure_falls_back(self, monkeypatch):
        from app.business.rag.retrieval.rerank import RerankClient

        def fake_post(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr("app.business.rag.retrieval.rerank.requests.post", fake_post)
        client = RerankClient(
            api_key="test-key",
            model="gated-rerank",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        scored = client.rerank("q", ["a", "b", "c"])
        assert [i for i, _ in scored] == [0, 1, 2]  # 降级保持原序


class TestRagToolDedup:
    """测试去重（设计 §7.3）。融合后直接结束，不额外调序。"""

    def _tool(self, **kw) -> RagRetrieveTool:
        from app.business.rag.retrieval.models import Document
        fake = MagicMock()
        fake.retrieve.return_value = [
            Document(id="1", content="退款政策A", metadata={"doc_type": "faq"}, score=0.9),
            Document(id="2", content="退款政策A", metadata={"doc_type": "policy"}, score=0.8),  # 同内容
            Document(id="3", content="物流说明", metadata={"doc_type": "help"}, score=0.85),
        ]
        return RagRetrieveTool(strategy=fake, **kw)

    def test_dedup_keeps_higher_score(self):
        tool = self._tool()
        res = tool.run(query="q")
        contents = [r["content"] for r in res]
        assert contents.count("退款政策A") == 1  # 去重
        kept = [r for r in res if r["content"] == "退款政策A"][0]
        assert kept["metadata"]["doc_type"] == "faq"  # 保留高分那份
