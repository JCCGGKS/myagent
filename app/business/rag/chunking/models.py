from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    """一个切块结果（所有分块策略共享的统一输出）。

    - ``chunk_no``：块序号（同一文档内从 0 递增）；
    - ``content``：切块正文；
    - ``heading_path``：结构切块时记录的层级路径（如 ["退款政策", "退款条件"]）；
    - ``doc_type``：内容类型（faq / policy / product ...）；
    - ``chunk_type``：块形态，text | table | clause（来自 05.3 §3）；
    - ``metadata``：策略附加的透传元数据（source / heading_path / table_id ...）。
    """

    chunk_no: int
    content: str
    heading_path: list[str] = field(default_factory=list)
    doc_type: str = "unknown"
    chunk_type: str = "text"          # text | table | clause
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_no": self.chunk_no,
            "content": self.content,
            "heading_path": self.heading_path,
            "doc_type": self.doc_type,
            "chunk_type": self.chunk_type,
            "metadata": self.metadata,
        }
