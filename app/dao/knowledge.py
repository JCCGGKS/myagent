from __future__ import annotations

from typing import Any

from app.pkgs.vector import QdrantClient, get_qdrant_client


class KnowledgeStore:
    """知识库向量存储（封装 pkgs.vector 的 qdrant 读写）。"""

    def __init__(self, client: QdrantClient | None = None) -> None:
        self._client = client or get_qdrant_client()

    def upsert_points(self, points: list[dict[str, Any]]) -> None:
        self._client.upsert(points)

    def create_collection(self, vector_size: int, distance: str = "Cosine") -> None:
        self._client.create_collection(vector_size, distance)

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return self._client.search_bm25(query, limit=limit)
