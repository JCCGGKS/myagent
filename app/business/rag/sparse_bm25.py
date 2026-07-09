from __future__ import annotations

import hashlib
import re
from typing import Any

# 稀疏向量词表大小（哈希空间）。BM25 的 IDF 由 Qdrant 在查询时按全局统计计算，
# 这里只需把词映射到稳定的非负索引即可，无需维护真实词表。
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
    """把文本转成 BM25 稀疏向量（仅存词频 TF，IDF 由 Qdrant 计算）。"""
    from qdrant_client.models import SparseVector

    tf: dict[int, float] = {}
    for tok in tokenize(text):
        idx = _token_index(tok)
        tf[idx] = tf.get(idx, 0.0) + 1.0

    indices = sorted(tf.keys())
    values = [tf[i] for i in indices]
    return SparseVector(indices=indices, values=values)
