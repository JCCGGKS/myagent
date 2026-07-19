from __future__ import annotations

from typing import Any

from app.business.rag.retrieval.base import RetrievalStrategy
from app.business.rag.retrieval.models import Document, documents_from_hits
from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("rag")

# --------------------------------------------------------------------------- #
# Qdrant / bm25 原生 BM25 稀疏向量
# --------------------------------------------------------------------------- #
# 采用官方 `Qdrant/bm25` FastEmbed 稀疏模型生成稀疏向量（分词 + 词频 + IDF
# 已烤进 values），写入 Qdrant 的 `bm25` 命名向量字段（SparseVectorParams
# modifier=Modifier.IDF），检索时由 Qdrant 原生打分。不再手搓倒排索引，
# 多 worker 下以 Qdrant 为唯一真源，避免内存索引各进程不一致。
_SPARSE_MODEL: Any = None


def _get_sparse_model() -> Any:
    """懒加载 FastEmbed 稀疏模型（进程内单例，首次调用时下载权重）。"""
    global _SPARSE_MODEL
    if _SPARSE_MODEL is None:
        from fastembed import SparseTextEmbedding

        _SPARSE_MODEL = SparseTextEmbedding(model_name="Qdrant/bm25")
    return _SPARSE_MODEL


def build_sparse_vector(text: str) -> "Any":
    """把文本转成 Qdrant 的 BM25 稀疏向量（SparseVector）。

    由 `Qdrant/bm25` FastEmbed 模型产出：分词 + 词频/IDF 权重已烤进 values，
    查询与入库共用，保证查询/文档同分布。检索时 Qdrant 再叠加 Modifier.IDF
    做集合级归一。FastEmbed 输出 numpy 数组，转成 Qdrant 所需的 list。
    """
    from qdrant_client.models import SparseVector

    if not text:
        return SparseVector(indices=[], values=[])
    emb = next(iter(_get_sparse_model().embed([text])))
    return SparseVector(
        indices=[int(i) for i in emb.indices.tolist()],
        values=[float(v) for v in emb.values.tolist()],
    )


# --------------------------------------------------------------------------- #
# 检索策略（包装 Qdrant 原生 bm25 稀疏向量检索）
# --------------------------------------------------------------------------- #
class BM25Strategy(RetrievalStrategy):
    """Qdrant 原生 BM25 关键词检索策略。

    通过 `client.search_sparse` 在 `bm25` 稀疏字段上检索，Qdrant 用
    Modifier.IDF 打分。client 为必传（BM25 打分已下沉到 Qdrant，不再有
    进程内倒排索引兜底）。
    """

    def __init__(
        self,
        client: Any,
        top_k: int = 5,
        min_score_threshold: float = 0.0,
    ) -> None:
        self.client = client
        self.top_k = top_k
        self.min_score_threshold = min_score_threshold

    def retrieve(self, query: str, user_id: int | None = None) -> list[Document]:
        """执行 Qdrant 原生 BM25 检索。"""
        logger.info(_tagged("rag", "BM25 native retrieve query=%r user_id=%s"), query, user_id)
        query_vec = build_sparse_vector(query)
        hits = self.client.search_sparse(
            query_sparse=query_vec,
            limit=max(self.top_k * 2, 20),
            score_threshold=self.min_score_threshold or None,
            user_id=user_id,
        )
        docs = documents_from_hits(hits, None)
        logger.info(_tagged("rag", "BM25 native end hits=%d"), len(docs))
        return docs
