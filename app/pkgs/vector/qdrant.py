from __future__ import annotations

import logging
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

    集合保存稠密向量（语义召回，dense 命名向量）与稀疏向量（BM25 关键词召回，
    bm25 命名向量）。BM25 关键词召回走 Qdrant 原生稀疏检索（Modifier.IDF），
    打分在服务端完成，无需进程内倒排索引，天然跨多 worker 一致。
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
        https: bool = False,
    ) -> None:
        from qdrant_client import QdrantClient as _RealClient

        self.host = host
        self.port = port
        self.collection_name = collection_name
        # qdrant-client 在 api_key 为非 None（哪怕是空串 ""）时会默认走 HTTPS；
        # 本地 Qdrant 为明文 HTTP，空串必须归一化为 None，否则会触发 TLS 握手失败
        #（[SSL: WRONG_VERSION_NUMBER]）。
        self.api_key = api_key or None
        self.https = https if api_key else False
        self.vector_size = vector_size
        self.distance = _DISTANCE_MAP.get(distance, "COSINE")
        self._client = _RealClient(
            host=host,
            port=port,
            api_key=self.api_key,
            prefer_grpc=prefer_grpc,
            https=self.https,
            timeout=10,
        )
        self._collection_ready = False

    # ------------------------------------------------------------------ #
    # 集合管理
    # ------------------------------------------------------------------ #
    def _ensure_collection(self) -> None:
        """懒创建集合（稠密向量 + 纯 BM25 模式的稀疏载体），仅首次访问时执行。

        稀疏向量仅作为「无 embedding 的纯 BM25 模式」下文档 point 的载体，
        不参与检索。若集合已存在但缺少该稀疏配置（旧 schema），在本地开发环境
        下重建，避免静默失败。生产环境应改为显式迁移。
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
                self._ensure_payload_indexes()
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
        self._ensure_payload_indexes()
        self._collection_ready = True

    def _ensure_payload_indexes(self) -> None:
        """为标量过滤字段建 keyword payload 索引（best-effort）。

        - doc_id：按文档删向量时过滤加速
        - user_id：按用户隔离检索时过滤加速

        索引已存在时 qdrant-client 会报错，忽略即可。
        """
        from qdrant_client.models import PayloadSchemaType

        for field in ("doc_id", "user_id"):
            try:
                self._client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("create_payload_index %s skipped: %r", field, exc)

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

    def delete_by_doc_id(self, doc_id: int) -> None:
        """按 doc_id 过滤删除一整篇文档的所有 chunk 向量。"""
        self._ensure_collection()
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            FilterSelector,
            MatchValue,
        )

        self._client.delete(
            collection_name=self.collection_name,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(key="doc_id", match=MatchValue(value=doc_id))
                    ]
                )
            ),
        )
        logger.info("deleted vectors for doc_id=%s from %s", doc_id, self.collection_name)

    # ------------------------------------------------------------------ #
    # 检索
    # ------------------------------------------------------------------ #
    def _user_filter(self, user_id: int | None) -> Any | None:
        """按 user_id 构造标量过滤（None 表示不过滤，全库召回）。"""
        if user_id is None:
            return None
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        return Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))])

    def search_semantic(
        self,
        query_vector: list[float],
        limit: int = 10,
        score_threshold: float | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_collection()
        result = self._client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            using=DENSE_VECTOR_NAME,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=self._user_filter(user_id),
            with_payload=True,
        )
        return [_hit_to_dict(h) for h in result.points]

    def search_sparse(
        self,
        query_sparse: Any,
        limit: int = 10,
        score_threshold: float | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """在 `bm25` 稀疏向量字段上做原生 BM25 检索（Qdrant Modifier.IDF 打分）。

        与 `search_semantic`（dense）并列；混合检索由 `search_hybrid` 融合。
        `query_sparse` 为 `SparseVector`（由 `build_sparse_vector` 产出）。
        """
        self._ensure_collection()
        from qdrant_client.models import SparseVector

        if not isinstance(query_sparse, SparseVector):
            query_sparse = SparseVector(indices=query_sparse[0], values=query_sparse[1])
        result = self._client.query_points(
            collection_name=self.collection_name,
            query=query_sparse,
            using=SPARSE_VECTOR_NAME,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=self._user_filter(user_id),
            with_payload=True,
        )
        return [_hit_to_dict(h) for h in result.points]

    def search_hybrid(
        self,
        dense_vec: list[float],
        sparse_vec: Any,
        limit: int = 10,
        rrf_k: int = 60,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """混合检索：dense + bm25 两路 prefetch，服务端 RRF 融合（Qdrant 原生）。

        单次请求完成语义与关键词召回的融合，避免客户端分两路 + 自写 RRF。
        `sparse_vec` 为 `SparseVector`（由 `build_sparse_vector` 产出）。
        `rrf_k` 经 `Rrf(k=...)` 下发到 Qdrant 的服务端 RRF 融合。
        """
        self._ensure_collection()
        from qdrant_client.models import Prefetch, Rrf, RrfQuery, SparseVector

        if not isinstance(sparse_vec, SparseVector):
            sparse_vec = SparseVector(indices=sparse_vec[0], values=sparse_vec[1])
        result = self._client.query_points(
            collection_name=self.collection_name,
            prefetch=[
                Prefetch(query=dense_vec, using=DENSE_VECTOR_NAME, limit=limit),
                Prefetch(query=sparse_vec, using=SPARSE_VECTOR_NAME, limit=limit),
            ],
            query=RrfQuery(rrf=Rrf(k=rrf_k)),
            limit=limit,
            query_filter=self._user_filter(user_id),
            with_payload=True,
        )
        return [_hit_to_dict(h) for h in result.points]

    def scroll_all(
        self,
        user_id: int | None = None,
        batch_size: int = 256,
    ) -> list[dict[str, Any]]:
        """滚动读取集合内全部点（按 user_id 可选过滤），返回 {id, payload} 列表。

        用于存量集合的稀疏向量回补 / 数据巡检等离线场景。
        """
        self._ensure_collection()
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        scroll_filter = self._user_filter(user_id)
        points: list[dict[str, Any]] = []
        next_offset: Any = None
        while True:
            batch, next_offset = self._client.scroll(
                collection_name=self.collection_name,
                scroll_filter=scroll_filter,
                limit=batch_size,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in batch:
                points.append({"id": p.id, "payload": p.payload or {}})
            if next_offset is None or not batch:
                break
        return points


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
    api_key = q.get("api_key") or None
    return QdrantClient(
        host=q.get("host", "localhost"),
        port=q.get("port", 6333),
        collection_name=q.get("collection_name", "customer_service_knowledge"),
        api_key=api_key,
        vector_size=q.get("vector_size", 1024),
        distance=q.get("distance", "COSINE"),
        https=api_key is not None,
    )
