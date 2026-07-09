from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from app.utils.config_paths import get_config_path


logger = logging.getLogger(__name__)


class QdrantClient:
    """Qdrant 连接管理（当前为模拟实现，后续接入真实 Qdrant）。"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "customer_service_knowledge",
    ) -> None:
        self.host = host
        self.port = port
        self.collection_name = collection_name

    def search_bm25(self, query: str, limit: int = 10, score_threshold: float | None = None) -> list[dict[str, Any]]:
        return [
            {
                "id": "mock_chunk_1",
                "content": f"模拟 BM25 检索结果: {query}",
                "metadata": {"doc_type": "faq", "title": "模拟文档"},
                "score": 8.5,
            }
        ]

    def search_semantic(self, query_vector: list[float], limit: int = 10, score_threshold: float | None = None, metric: str = "cosine") -> list[dict[str, Any]]:
        return [
            {
                "id": "mock_chunk_2",
                "content": f"模拟语义检索结果: {query_vector[:3]}...",
                "metadata": {"doc_type": "policy", "title": "模拟政策文档"},
                "score": 0.85,
            }
        ]

    def search_hybrid(self, query: str, query_vector: list[float], limit: int = 10, fusion_method: str = "rrf") -> list[dict[str, Any]]:
        return [
            {
                "id": "mock_chunk_3",
                "content": f"模拟混合检索结果: {query}",
                "metadata": {"doc_type": "faq", "title": "模拟混合文档"},
                "score": 0.75,
            }
        ]

    def create_collection(self, vector_size: int, distance: str = "Cosine") -> None:
        self._memory: dict[str, Any] = {}
        logger.info("Mock create_collection: %s size=%d", self.collection_name, vector_size)

    def upsert(self, points: list[dict[str, Any]]) -> None:
        if not hasattr(self, "_memory"):
            self._memory = {}
        for p in points:
            self._memory[p["id"]] = p
        logger.info("Mock upsert %d points into %s", len(points), self.collection_name)


def _read_qdrant_config() -> dict[str, Any]:
    """读取 qdrant 配置（rag.qdrant 段）。未配置则回退默认。"""
    for path in [get_config_path(), get_config_path("local")]:
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            rag = data.get("rag")
            if isinstance(rag, dict):
                q = rag.get("qdrant")
                if isinstance(q, dict):
                    return q
    return {}


def get_qdrant_client() -> QdrantClient:
    """根据配置创建 Qdrant 客户端（配置了就是启用；字段缺失用默认）。"""
    cfg = _read_qdrant_config()
    return QdrantClient(
        host=cfg.get("host", "localhost"),
        port=cfg.get("port", 6333),
        collection_name=cfg.get("collection_name", "customer_service_knowledge"),
    )
