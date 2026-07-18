from __future__ import annotations

import math
import re
import hashlib
from collections import defaultdict
from typing import Any

from app.business.rag.retrieval.base import RetrievalStrategy
from app.business.rag.retrieval.models import Document, documents_from_hits
from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("rag")

# --------------------------------------------------------------------------- #
# 分词 + Qdrant 稀疏向量（BM25 命名向量的写入 / 查询共用）
# --------------------------------------------------------------------------- #
# 稀疏向量词表大小（哈希空间）。Qdrant bm25 命名向量走 Modifier.IDF，
# 这里只需把词映射到稳定非负索引即可，无需维护真实词表。
VOCAB_SIZE = 1 << 20  # 1048576

# 英文/数字按词切，中文按字切（MVP 简化分词，template/rag.md 亦指出中文分词较弱可接受）
_TOKEN_RE = re.compile(r"[a-z0-9]+|[一-鿿]")


def tokenize(text: str) -> list[str]:
    """简单分词：小写 ASCII 词 + 单个汉字。"""
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


def _token_index(token: str) -> int:
    """将词稳定映射为非负索引（避免 hash 负值）。"""
    digest = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % VOCAB_SIZE


def build_sparse_vector(text: str) -> "Any":
    """把文本转成 Qdrant 的 BM25 稀疏向量（仅存词频 TF，IDF 由 Qdrant 计算）。

    仅用于 Qdrant bm25 命名向量（入库写入 + 查询时构造 query 向量）。
    手搓倒排索引（BM25Index）不依赖此函数，而是直接对 tokenize 结果计 TF 并现算 IDF。
    """
    from qdrant_client.models import SparseVector

    tf: dict[int, float] = {}
    for tok in tokenize(text):
        idx = _token_index(tok)
        tf[idx] = tf.get(idx, 0.0) + 1.0

    indices = sorted(tf.keys())
    values = [tf[i] for i in indices]
    return SparseVector(indices=indices, values=values)


# --------------------------------------------------------------------------- #
# 手搓 BM25 倒排索引（IDF / avgdl 一律现算，向量里不烤全局量）
# --------------------------------------------------------------------------- #
class BM25Index:
    """单用户的 BM25 倒排索引（手搓，IDF / avgdl 查询时现算，向量里不烤全局量）。

    结构（见设计）：
      inverted : dict[term -> list[(chunk_id, tf)]]  # 倒排；n_t = len(inverted[t]) 免费得到
      doc_len  : dict[chunk_id -> |d|]
      doc_text : dict[chunk_id -> list[term]]  # 仅 delete 找词集 / 调试
      doc_raw  : dict[chunk_id -> str]          # 原始文本，回传 content 用
      doc_meta : dict[chunk_id -> dict]          # 回传 metadata
      N         : int                                 # 文档数
      total_tokens: int                               # 总 token 数 -> avgdl

    IDF(t) = log((N - n_t + 0.5)/(n_t + 0.5) + 1)，n_t = len(inverted[t])，查询时现算。
    """

    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.inverted: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self.doc_len: dict[str, int] = {}
        self.doc_text: dict[str, list[str]] = {}
        self.doc_raw: dict[str, str] = {}
        self.doc_meta: dict[str, dict[str, Any]] = {}
        self.N = 0
        self.total_tokens = 0

    # ------------------------------------------------------------------ #
    # 增量写
    # ------------------------------------------------------------------ #
    def add(
        self,
        chunk_id: str,
        tokens: list[str],
        content: str,
        meta: dict[str, Any],
    ) -> None:
        """新增一个 chunk 到索引。幂等：同 chunk_id 先按 delete 处理。"""
        if chunk_id in self.doc_len:
            self.delete(chunk_id)
        if not tokens:
            return
        self.N += 1
        self.total_tokens += len(tokens)
        self.doc_len[chunk_id] = len(tokens)
        self.doc_text[chunk_id] = list(tokens)
        self.doc_raw[chunk_id] = content
        self.doc_meta[chunk_id] = meta or {}
        tf = defaultdict(int)
        for t in tokens:
            tf[t] += 1
        for t, c in tf.items():
            self.inverted[t].append((chunk_id, c))

    def delete(self, chunk_id: str) -> None:
        """从索引移除一个 chunk。"""
        tokens = self.doc_text.pop(chunk_id, None)
        if tokens is None:
            return
        self.N -= 1
        self.total_tokens -= self.doc_len.pop(chunk_id, 0)
        self.doc_raw.pop(chunk_id, None)
        self.doc_meta.pop(chunk_id, None)
        for t in set(tokens):
            lst = self.inverted.get(t)
            if lst is None:
                continue
            self.inverted[t] = [(d, c) for (d, c) in lst if d != chunk_id]
            if not self.inverted[t]:
                del self.inverted[t]

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def search(
        self,
        query: str,
        top_k: int,
        min_score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """执行 BM25 检索，返回命中字典列表（与 Qdrant hit 同构，便于复用 documents_from_hits）。"""
        q_tokens = tokenize(query)
        if self.N == 0 or not q_tokens:
            return []
        avgdl = self.total_tokens / self.N
        scores: dict[str, float] = defaultdict(float)
        for t in set(q_tokens):
            postings = self.inverted.get(t)
            if not postings:
                continue
            n_t = len(postings)  # n_t = 倒排列表长度
            idf = math.log((self.N - n_t + 0.5) / (n_t + 0.5) + 1.0)
            for chunk_id, tf in postings:
                dl = self.doc_len[chunk_id]
                denom = tf + self.k1 * (1 - self.b + self.b * dl / avgdl)
                sat = tf * (self.k1 + 1) / denom
                scores[chunk_id] += idf * sat
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        out: list[dict[str, Any]] = []
        for chunk_id, score in ranked:
            if min_score_threshold is not None and score < min_score_threshold:
                continue
            out.append(
                {
                    "id": chunk_id,
                    "content": self.doc_raw.get(chunk_id, ""),
                    "metadata": self.doc_meta.get(chunk_id, {}),
                    "score": score,
                }
            )
        return out

    def __len__(self) -> int:
        return self.N


class BM25Store:
    """跨请求持有的 BM25 索集合（per user_id），单例。

    内存索引：进程重启后为空，可调用 rebuild_from_qdrant 从 Qdrant 重建。
    """

    def __init__(self) -> None:
        self._indexes: dict[Any, BM25Index] = {}
        # doc_id -> [user_id, {chunk_id, ...}]，用于按文档整体删除
        self._doc_map: dict[Any, list[Any]] = defaultdict(lambda: [None, set()])

    def get_index(self, user_id: Any) -> BM25Index:
        idx = self._indexes.get(user_id)
        if idx is None:
            idx = BM25Index()
            self._indexes[user_id] = idx
        return idx

    def add(
        self,
        chunk_id: str,
        tokens: list[str],
        content: str,
        meta: dict[str, Any],
        user_id: Any,
        doc_id: Any = None,
    ) -> None:
        self.get_index(user_id).add(chunk_id, tokens, content, meta)
        if doc_id is not None:
            entry = self._doc_map[doc_id]
            entry[0] = user_id
            entry[1].add(chunk_id)

    def delete_doc(self, doc_id: Any) -> None:
        entry = self._doc_map.pop(doc_id, None)
        if entry is None:
            return
        user_id, chunk_ids = entry[0], entry[1]
        idx = self.get_index(user_id)
        for chunk_id in chunk_ids:
            idx.delete(chunk_id)

    def rebuild_from_qdrant(self, client: Any, user_id: Any = None) -> int:
        """从 Qdrant 全量重建（滚动读取 payload，按 content 重新分词建索引）。

        进程重启后内存索引为空时调用；返回重建的 chunk 数。
        """
        points = client.scroll_all(user_id=user_id)
        count = 0
        for p in points:
            payload = p.get("payload") or {}
            content = payload.get("content", "")
            if not content:
                continue
            self.add(
                chunk_id=str(p.get("id")),
                tokens=tokenize(content),
                content=content,
                meta=payload,
                user_id=payload.get("user_id"),
                doc_id=payload.get("doc_id"),
            )
            count += 1
        logger.info("bm25 rebuild_from_qdrant user_id=%s chunks=%d", user_id, count)
        return count

    def __len__(self) -> int:
        return sum(len(i) for i in self._indexes.values())


# 模块级单例
_bm25_store = BM25Store()


def get_bm25_store() -> BM25Store:
    return _bm25_store


# --------------------------------------------------------------------------- #
# 检索策略（包装手搓 BM25 倒排索引，符合 RetrievalStrategy 接口）
# --------------------------------------------------------------------------- #
class BM25Strategy(RetrievalStrategy):
    """手搓 BM25 关键词检索策略（倒排索引，IDF / avgdl 现算）。

    与原先走 Qdrant Modifier.IDF 点积的 BM25Strategy 不同：本策略直接对内存倒排
    索引做 BM25 求和，分数即真·BM25，无需把全局量烤进向量，也不依赖 Qdrant
    稀疏向量检索。k1 / b 由 RagConfig.bm25_k1 / bm25_b 注入。
    """

    def __init__(
        self,
        client: Any | None = None,
        top_k: int = 5,
        min_score_threshold: float = 0.0,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> None:
        # client 仅用于进程重启后的一次性索引重建（lazy rebuild），可为 None。
        self.client = client
        self.top_k = top_k
        self.min_score_threshold = min_score_threshold
        self.k1 = k1
        self.b = b

    def retrieve(self, query: str, user_id: int | None = None) -> list[Document]:
        """执行手搓 BM25 检索。"""
        logger.info(_tagged("rag", "BM25 native retrieve query=%r user_id=%s"), query, user_id)
        store = get_bm25_store()
        idx = store.get_index(user_id)
        # 进程重启后内存索引为空：一次性从 Qdrant 重建（best-effort）。
        if len(idx) == 0 and self.client is not None:
            store.rebuild_from_qdrant(self.client, user_id=user_id)
            idx = store.get_index(user_id)
        # 应用当前 k1 / b（支持运行时经 RagConfig 调整）。
        idx.k1 = self.k1
        idx.b = self.b
        hits = idx.search(query, top_k=self.top_k, min_score_threshold=self.min_score_threshold)
        docs = documents_from_hits(hits, None)
        logger.info(_tagged("rag", "BM25 native end hits=%d"), len(docs))
        return docs
