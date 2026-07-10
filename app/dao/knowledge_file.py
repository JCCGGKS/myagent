from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any


class KnowledgeFileDAO(ABC):
    """知识库文件元信息数据访问接口（dao 层）。"""

    @abstractmethod
    def create(
        self,
        user_id: int,
        filename: str,
        file_size: int,
        doc_type: str,
        status: int = 0,
        chunk_count: int = 0,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    def list_by_user(self, user_id: int) -> list[dict[str, Any]]:
        """列出某用户的文件（排除软删除项），按 id 倒序。"""

    @abstractmethod
    def get_by_id(self, file_id: int) -> dict[str, Any] | None:
        ...

    @abstractmethod
    def update_status(
        self,
        file_id: int,
        status: int,
        chunk_count: int | None = None,
        error_message: str | None = None,
    ) -> None:
        ...

    @abstractmethod
    def delete(self, file_id: int) -> None:
        """软删除：标记 deleted_at，不物理删除。"""


class MemoryKnowledgeFileDAO(KnowledgeFileDAO):
    """内存实现（本地/测试默认）。"""

    def __init__(self) -> None:
        self._by_id: dict[int, dict[str, Any]] = {}
        self._seq: int = 0

    def create(
        self,
        user_id: int,
        filename: str,
        file_size: int,
        doc_type: str,
        status: int = 0,
        chunk_count: int = 0,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        self._seq += 1
        record = {
            "id": self._seq,
            "user_id": user_id,
            "filename": filename,
            "file_size": file_size,
            "doc_type": doc_type,
            "chunk_count": chunk_count,
            "status": status,
            "error_message": error_message,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "deleted_at": None,
        }
        self._by_id[self._seq] = record
        return dict(record)

    def list_by_user(self, user_id: int) -> list[dict[str, Any]]:
        result = [
            dict(r)
            for r in self._by_id.values()
            if r["user_id"] == user_id and r.get("deleted_at") is None
        ]
        result.sort(key=lambda r: r.get("id", 0), reverse=True)
        return result

    def get_by_id(self, file_id: int) -> dict[str, Any] | None:
        rec = self._by_id.get(file_id)
        if rec is None or rec.get("deleted_at") is not None:
            return None
        return dict(rec)

    def update_status(
        self,
        file_id: int,
        status: int,
        chunk_count: int | None = None,
        error_message: str | None = None,
    ) -> None:
        rec = self._by_id.get(file_id)
        if rec is None:
            return
        rec["status"] = status
        rec["updated_at"] = datetime.now(UTC)
        if chunk_count is not None:
            rec["chunk_count"] = chunk_count
        if error_message is not None:
            rec["error_message"] = error_message

    def delete(self, file_id: int) -> None:
        rec = self._by_id.get(file_id)
        if rec is not None:
            rec["deleted_at"] = datetime.now(UTC)


class SqlKnowledgeFileDAO(KnowledgeFileDAO):
    """MySQL 实现（配置了 mysql 段时注入）。"""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def _db(self):
        return self._session_factory()

    @staticmethod
    def _to_dict(row: Any) -> dict[str, Any]:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "filename": row.filename,
            "file_size": row.file_size,
            "doc_type": row.doc_type,
            "chunk_count": row.chunk_count,
            "status": row.status,
            "error_message": row.error_message,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "deleted_at": row.deleted_at,
        }

    def create(
        self,
        user_id: int,
        filename: str,
        file_size: int,
        doc_type: str,
        status: int = 0,
        chunk_count: int = 0,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        with self._db() as db:
            from app.model.knowledge import KnowledgeFile

            row = KnowledgeFile(
                user_id=user_id,
                filename=filename,
                file_size=file_size,
                doc_type=doc_type,
                chunk_count=chunk_count,
                status=status,
                error_message=error_message,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._to_dict(row)

    def list_by_user(self, user_id: int) -> list[dict[str, Any]]:
        with self._db() as db:
            from app.model.knowledge import KnowledgeFile

            rows = (
                db.query(KnowledgeFile)
                .filter(KnowledgeFile.user_id == user_id)
                .filter(KnowledgeFile.deleted_at.is_(None))
                .order_by(KnowledgeFile.id.desc())
                .all()
            )
            return [self._to_dict(r) for r in rows]

    def get_by_id(self, file_id: int) -> dict[str, Any] | None:
        with self._db() as db:
            from app.model.knowledge import KnowledgeFile

            row = db.get(KnowledgeFile, file_id)
            if row is None or row.deleted_at is not None:
                return None
            return self._to_dict(row)

    def update_status(
        self,
        file_id: int,
        status: int,
        chunk_count: int | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._db() as db:
            from app.model.knowledge import KnowledgeFile

            row = db.get(KnowledgeFile, file_id)
            if row is None:
                return
            row.status = status
            if chunk_count is not None:
                row.chunk_count = chunk_count
            if error_message is not None:
                row.error_message = error_message
            db.commit()

    def delete(self, file_id: int) -> None:
        with self._db() as db:
            from app.model.knowledge import KnowledgeFile
            from sqlalchemy import update

            db.execute(
                update(KnowledgeFile)
                .where(KnowledgeFile.id == file_id)
                .values(deleted_at=datetime.now(UTC))
            )
            db.commit()
