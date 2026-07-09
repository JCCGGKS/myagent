from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from app.utils.config_paths import get_config_path


logger = logging.getLogger(__name__)

# 命名向量：稠密（语义）+ 稀疏（BM25）
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "bm25"

# 语义检索距离度量 -> Qdrant Distance 枚举名
_DISTANCE_MAP = {
    "cosine": "COSINE",
    "dot_product": "DOT",
    "euclidean": "EUCLID",
}


class QdrantClient:
    """Qdrant 客户端封装（基于 qdrant-client，连接真实 Qdrant 实例）。

    集合同时保存稠密向量（语义召回）与稀疏向量（BM25 关键词召回，
    modifier=IDF 由 Qdrant 维护全局 IDF）。混合检索使用 Qdrant 原生 RRF 融合。
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "customer_service_knowledge",
        api_key: str | None = None,
        vector_size: int = 1024,
        distance: str = "COSINE",
        prefer_grpc: bool = False,
    ) -> None:
        from qdrant_client import QdrantClient as _RealClient

        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.api_key = api_key
        self.vector_size = vector_size
        self.distance = _DISTANCE_MAP.get(distance, "COSINE")
        self._client = _RealClient(
            host=host,
            port=port,
            api_key=api_key,
            prefer_grpc=prefer_grpc,
            timeout=10,
        )
        self._collection_ready = False

    # ------------------------------------------------------------------ #
    # 集合管理
    # ------------------------------------------------------------------ #
    def _ensure_collection(self) -> None:
        """懒创建集合（稠密 + BM25 稀疏向量），仅首次访问时执行。

        若集合已存在但缺少 BM25 稀疏向量（旧 schema），在本地开发环境下重建，
        避免静默失败。生产环境应改为显式迁移。
        """
        if self._collection_ready:
            return
        from qdrant_client.models import (
            Distance,
            Modifier,
            SparseVectorParams,
            VectorParams,
        )

        if self._client.collection_exists(self.collection_name):
            if not self._has_sparse_vector():
                logger.warning(
                    "collection %s 缺少稀疏向量 %s，重建以应用新 schema",
                    self.collection_name,
                    SPARSE_VECTOR_NAME,
                )
                self._client.delete_collection(self.collection_name)
            else:
                self._collection_ready = True
                return

        self._client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                DENSE_VECTOR_NAME: VectorParams(
                    size=self.vector_size,
                    distance=Distance[self.distance],
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF)
            },
        )
        logger.info("created collection %s (dense+sparse/bm25)", self.collection_name)
        self._collection_ready = True

    def _has_sparse_vector(self) -> bool:
        """检查集合是否已包含 BM25 稀疏向量配置。"""
        try:
            info = self._client.get_collection(self.collection_name)
            sparse = info.config.params.sparse_vectors
        except Exception:
            return False
        if not sparse:
            return False
        names = (
            list(sparse.keys())
            if isinstance(sparse, dict)
            else [v.name for v in sparse]
        )
        return SPARSE_VECTOR_NAME in names

    def create_collection(self, vector_size: int, distance: str = "COSINE") -> None:
        self.vector_size = vector_size
        self.distance = _DISTANCE_MAP.get(distance, "COSINE")
        self._collection_ready = False
        self._ensure_collection()

    def upsert(self, points: list[dict[str, Any]]) -> None:
        self._ensure_collection()
        from qdrant_client.models import PointStruct

        structs = [
            PointStruct(
                id=p["id"],
                vector=p["vector"],  # 命名向量 dict: {"dense": [...], "bm25": SparseVector}
                payload=p.get("payload", {}),
            )
            for p in points
        ]
        if not structs:
            return
        self._client.upsert(collection_name=self.collection_name, points=structs)
        logger.info("upsert %d points into %s", len(structs), self.collection_name)

    # ------------------------------------------------------------------ #
    # 检索
    # ------------------------------------------------------------------ #
    def search_semantic(
        self,
        query_vector: list[float],
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_collection()
        result = self._client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            using=DENSE_VECTOR_NAME,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )
        return [_hit_to_dict(h) for h in result.points]

    def search_bm25(
        self,
        query: str,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_collection()
        from app.business.rag.sparse_bm25 import build_sparse_vector

        sparse = build_sparse_vector(query)
        result = self._client.query_points(
            collection_name=self.collection_name,
            query=sparse,
            using=SPARSE_VECTOR_NAME,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )
        return [_hit_to_dict(h) for h in result.points]

    def search_hybrid(
        self,
        query: str,
        query_vector: list[float],
        limit: int = 10,
        fusion_method: str = "rrf",
    ) -> list[dict[str, Any]]:
        """混合检索：Qdrant 原生 prefetch + RRF 融合（稠密 + BM25 稀疏）。"""
        self._ensure_collection()
        from app.business.rag.sparse_bm25 import build_sparse_vector
        from qdrant_client.models import Fusion, FusionQuery, Prefetch

        fusion = Fusion.RRF if fusion_method == "rrf" else Fusion.DBSF
        sparse = build_sparse_vector(query)
        result = self._client.query_points(
            collection_name=self.collection_name,
            prefetch=[
                Prefetch(query=sparse, using=SPARSE_VECTOR_NAME, limit=limit),
                Prefetch(query=query_vector, using=DENSE_VECTOR_NAME, limit=limit),
            ],
            query=FusionQuery(fusion=fusion),
            limit=limit,
            with_payload=True,
        )
        return [_hit_to_dict(h) for h in result.points]


def _hit_to_dict(hit: Any) -> dict[str, Any]:
    """将 Qdrant ScoredPoint 转为统一检索结果字典。"""
    payload = hit.payload or {}
    metadata = dict(payload.get("metadata", {}) or {})
    if payload.get("doc_type") is not None:
        metadata["doc_type"] = payload["doc_type"]
    if payload.get("heading_path") is not None:
        metadata["heading_path"] = payload["heading_path"]
    if payload.get("user_id") is not None:
        metadata["user_id"] = payload["user_id"]
    return {
        "id": str(hit.id),
        "content": payload.get("content", ""),
        "metadata": metadata,
        "score": hit.score,
    }


def _read_qdrant_config() -> dict[str, Any]:
    """读取 qdrant 配置（config 文件的顶层段，与 rag 同级）。

    local 覆盖文件的同名键会叠加。embedding 配置由 app.config.rag_config
    单独读取，这里不涉及。
    """
    qdrant_cfg: dict[str, Any] = {}
    for path in [get_config_path(), get_config_path("local")]:
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("qdrant"), dict):
            qdrant_cfg.update(data["qdrant"])
    return qdrant_cfg


def get_qdrant_client() -> QdrantClient:
    """根据配置创建 Qdrant 客户端。

    读取顶层 qdrant 段（host/port/collection_name/api_key/distance/vector_size）；
    缺失则用默认值。向量维度以 qdrant.vector_size 为准，须与嵌入模型输出维度一致。
    """
    q = _read_qdrant_config()
    return QdrantClient(
        host=q.get("host", "localhost"),
        port=q.get("port", 6333),
        collection_name=q.get("collection_name", "customer_service_knowledge"),
        api_key=q.get("api_key"),
        vector_size=q.get("vector_size", 1024),
        distance=q.get("distance", "COSINE"),
    )
