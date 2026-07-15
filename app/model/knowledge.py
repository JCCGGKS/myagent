from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.model import Base


# knowledge_files.status 枚举（TINYINT）
KNOWLEDGE_FILE_STATUS_PROCESSING = 0
KNOWLEDGE_FILE_STATUS_SUCCESS = 1
KNOWLEDGE_FILE_STATUS_ERROR = 2


class KnowledgeFile(Base):
    """知识库文件元信息。

    id 同时作为文档标识 doc_id（写入 Qdrant payload，按文档删向量）；
    删除为软删除（标记 deleted_at），列表查询过滤已删除项。
    content_hash 为「user_id + 文件内容」的 SHA-256，配合 (user_id, content_hash)
    唯一约束实现上传幂等：相同用户上传相同内容不会重复落库/重复向量化。
    """

    __tablename__ = "knowledge_files"
    __table_args__ = (
        UniqueConstraint("user_id", "content_hash", name="uq_kf_user_content_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, default=0)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
