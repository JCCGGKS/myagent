from __future__ import annotations

from typing import Any


class Document:
    """检索结果文档。"""

    def __init__(self, id: str, content: str, metadata: dict[str, Any], score: float) -> None:
        self.id = id
        self.content = content
        self.metadata = metadata
        self.score = score

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "metadata": self.metadata,
            "score": self.score,
        }


def documents_from_hits(
    hits: list[dict[str, Any]], threshold: float | None = None
) -> list["Document"]:
    """把 Qdrant 命中字典列表转为 Document 列表，并按阈值过滤低分命中。

    bm25 / semantic 两路召回的命中结构一致，统一在此转换，避免各自重复构造。
    """
    docs: list[Document] = []
    for hit in hits:
        score = hit.get("score", 0.0)
        if threshold is not None and score < threshold:
            continue
        docs.append(
            Document(
                id=hit["id"],
                content=hit["content"],
                metadata=hit["metadata"],
                score=score,
            )
        )
    return docs
