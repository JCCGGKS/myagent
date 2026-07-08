from __future__ import annotations

import logging
from typing import Any, Optional
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)


class QdrantClient:
    """Qdrant 连接管理（当前为模拟实现，后续接入真实 Qdrant）。"""

    def __init__(self, host: str = "localhost", port: int = 6333, collection_name: str = "customer_service_knowledge") -> None:
        self.host = host
        self.port = port
        self.collection_name = collection_name
        # TODO: 后续接入真实 Qdrant 客户端
        # from qdrant_client import QdrantClient as RealQdrantClient
        # self.client = RealQdrantClient(host=host, port=port)

    def search_bm25(self, query: str, limit: int = 10, score_threshold: Optional[float] = None) -> list[dict[str, Any]]:
        """BM25 关键词检索（模拟实现）。"""
        # TODO: 接入真实 Qdrant BM25 检索
        # return self.client.search(
        #     collection_name=self.collection_name,
        #     query=query,
        #     using="bm25",
        #     limit=limit,
        #     score_threshold=score_threshold,
        # )
        return [
            {
                "id": "mock_chunk_1",
                "content": f"模拟 BM25 检索结果: {query}",
                "metadata": {"doc_type": "faq", "title": "模拟文档"},
                "score": 8.5,
            }
        ]

    def search_semantic(self, query_vector: list[float], limit: int = 10, score_threshold: Optional[float] = None, metric: str = "cosine") -> list[dict[str, Any]]:
        """语义向量检索（模拟实现）。"""
        # TODO: 接入真实 Qdrant 向量检索
        # return self.client.search(
        #     collection_name=self.collection_name,
        #     query_vector=query_vector,
        #     using="dense_vector",
        #     limit=limit,
        #     score_threshold=score_threshold,
        # )
        return [
            {
                "id": "mock_chunk_2",
                "content": f"模拟语义检索结果: {query_vector[:3]}...",
                "metadata": {"doc_type": "policy", "title": "模拟政策文档"},
                "score": 0.85,
            }
        ]

    def search_hybrid(self, query: str, query_vector: list[float], limit: int = 10, fusion_method: str = "rrf") -> list[dict[str, Any]]:
        """混合检索（模拟实现）。"""
        # TODO: 接入真实 Qdrant 混合检索
        # prefetch_bm25 = {"query": query, "using": "bm25", "limit": limit * 2}
        # prefetch_semantic = {"query_vector": query_vector, "using": "dense_vector", "limit": limit * 2}
        # return self.client.hybrid_search(
        #     collection_name=self.collection_name,
        #     prefetch=[prefetch_bm25, prefetch_semantic],
        #     fusion_type=fusion_method,
        #     limit=limit,
        # )
        return [
            {
                "id": "mock_chunk_3",
                "content": f"模拟混合检索结果: {query}",
                "metadata": {"doc_type": "faq", "title": "模拟混合文档"},
                "score": 0.75,
            }
        ]

    def create_collection(self, vector_size: int, distance: str = "Cosine") -> None:
        """创建 Collection（模拟实现：仅记录参数）。"""
        # TODO: 接入真实 Qdrant
        # self.client.create_collection(
        #     collection_name=self.collection_name,
        #     vectors_config=VectorParams(size=vector_size, distance=distance),
        # )
        self._memory: dict[str, Any] = {}  # 模拟存储
        logger.info("Mock create_collection: %s size=%d", self.collection_name, vector_size)

    def upsert(self, points: list[dict[str, Any]]) -> None:
        """写入向量点（模拟实现：存到内存字典）。

        points 每项: {"id": str, "vector": list[float], "payload": dict}
        """
        # TODO: 接入真实 Qdrant
        # self.client.upsert(collection_name=self.collection_name, points=points)
        if not hasattr(self, "_memory"):
            self._memory = {}
        for p in points:
            self._memory[p["id"]] = p
        logger.info("Mock upsert %d points into %s", len(points), self.collection_name)


def get_qdrant_client() -> QdrantClient:
    """从配置文件中读取 Qdrant 配置，创建客户端。"""
    config_path = Path(__file__).resolve().parents[2] / "config" / "llm_config.local.yml"
    if not config_path.exists():
        # 如果本地配置不存在，使用默认值
        return QdrantClient()

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    rag_config = config.get("rag", {})
    qdrant_config = rag_config.get("qdrant", {})
    return QdrantClient(
        host=qdrant_config.get("host", "localhost"),
        port=qdrant_config.get("port", 6333),
        collection_name=qdrant_config.get("collection_name", "customer_service_knowledge"),
    )
