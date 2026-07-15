from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError


class DuplicateKnowledgeFileError(Exception):
    """同一 (user_id, content_hash) 已存在未删除记录时抛出（幂等硬关卡）。

    由 (user_id, content_hash) 唯一约束触发，调用方据此回退到「查已有记录 → 状态机分流」，
    避免在并发上传同一文件时插出第二条记录、重复向量化。
    """


class KnowledgeFileDAO(ABC):
    """知识库文件元信息数据访问接口（dao 层）。

    M2 起所有方法均为 ``async def``，底层使用 ``AsyncSession``，I/O 等待时
    让出事件循环（详见 plans/full-async-plan.md）。内存实现同样为 async，仅逻辑同步。
    """

    @abstractmethod
    async def create(
        self,
        user_id: int,
        filename: str,
        file_size: int,
        doc_type: str,
        status: int = 0,
        chunk_count: int = 0,
        error_message: str | None = None,
        content_hash: str = "",
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    async def find_by_content_hash(
        self, user_id: int, content_hash: str
    ) -> dict[str, Any] | None:
        """按 (user_id, content_hash) 查未软删除的最新一条（任意状态），查不到返回 None。"""

    @abstractmethod
    async def list_by_user(self, user_id: int) -> list[dict[str, Any]]:
        """列出某用户的文件（排除软删除项），按 id 倒序。"""

    @abstractmethod
    async def get_by_id(self, file_id: int) -> dict[str, Any] | None:
        ...

    @abstractmethod
    async def update_status(
        self,
        file_id: int,
        status: int,
        chunk_count: int | None = None,
        error_message: str | None = None,
        refresh_created_at: bool = False,
    ) -> None:
        ...

    @abstractmethod
    async def delete(self, file_id: int) -> None:
        """软删除：标记 deleted_at，不物理删除。"""

    @abstractmethod
    async def update_content(
        self, file_id: int, content_hash: str, filename: str, file_size: int, doc_type: str
    ) -> None:
        """更新文件内容相关元信息（content_hash / filename / file_size / doc_type）并刷新 updated_at。

        用于「更新文件」接口：重建向量后同步新内容哈希，保持幂等键一致。
        若新 content_hash 与「其他」未软删记录冲突，抛 DuplicateKnowledgeFileError。
        """


class MemoryKnowledgeFileDAO(KnowledgeFileDAO):
    """内存实现（本地/测试默认）。"""

    def __init__(self) -> None:
        self._by_id: dict[int, dict[str, Any]] = {}
        self._seq: int = 0

    async def create(
        self,
        user_id: int,
        filename: str,
        file_size: int,
        doc_type: str,
        status: int = 0,
        chunk_count: int = 0,
        error_message: str | None = None,
        content_hash: str = "",
    ) -> dict[str, Any]:
        # 内存实现下同步校验唯一约束（事件循环单线程，await 间隙仍可能被其他协程插入）。
        # 仅对非空真实哈希做校验（空串为未指定哈希的占位，不参与去重）。
        if content_hash:
            for rec in self._by_id.values():
                if (
                    rec.get("deleted_at") is None
                    and rec["user_id"] == user_id
                    and rec.get("content_hash") == content_hash
                ):
                    raise DuplicateKnowledgeFileError(
                        f"duplicate content_hash {content_hash} for user {user_id}"
                    )
        self._seq += 1
        record = {
            "id": self._seq,
            "user_id": user_id,
            "filename": filename,
            "file_size": file_size,
            "doc_type": doc_type,
            "content_hash": content_hash,
            "chunk_count": chunk_count,
            "status": status,
            "error_message": error_message,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "deleted_at": None,
        }
        self._by_id[self._seq] = record
        return dict(record)

    async def find_by_content_hash(
        self, user_id: int, content_hash: str
    ) -> dict[str, Any] | None:
        matched = [
            dict(r)
            for r in self._by_id.values()
            if r["user_id"] == user_id
            and r.get("content_hash") == content_hash
            and r.get("deleted_at") is None
        ]
        if not matched:
            return None
        matched.sort(key=lambda r: r["id"], reverse=True)
        return matched[0]

    async def list_by_user(self, user_id: int) -> list[dict[str, Any]]:
        result = [
            dict(r)
            for r in self._by_id.values()
            if r["user_id"] == user_id and r.get("deleted_at") is None
        ]
        result.sort(key=lambda r: r.get("id", 0), reverse=True)
        return result

    async def get_by_id(self, file_id: int) -> dict[str, Any] | None:
        rec = self._by_id.get(file_id)
        if rec is None or rec.get("deleted_at") is not None:
            return None
        return dict(rec)

    async def update_status(
        self,
        file_id: int,
        status: int,
        chunk_count: int | None = None,
        error_message: str | None = None,
        refresh_created_at: bool = False,
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
        if refresh_created_at:
            rec["created_at"] = datetime.now(UTC)

    async def delete(self, file_id: int) -> None:
        rec = self._by_id.get(file_id)
        if rec is not None:
            # 软删除保留哈希槽位：写入「DELETED:{id}」哨兵（非 NULL、且按主键全局唯一），
            # 既不触发 NOT NULL 约束，也不会在多文件删除时撞 (user_id, content_hash) 唯一键。
            # 删除后重传相同内容：查重查不到哨兵，自然新建一条记录重新向量化。
            rec["content_hash"] = f"DELETED:{file_id}"
            rec["deleted_at"] = datetime.now(UTC)

    async def update_content(
        self, file_id: int, content_hash: str, filename: str, file_size: int, doc_type: str
    ) -> None:
        rec = self._by_id.get(file_id)
        if rec is None:
            return
        # 唯一约束校验：排除自身，避免更新后与他人 (user_id, content_hash) 撞键
        for other in self._by_id.values():
            if (
                other["id"] != file_id
                and other.get("deleted_at") is None
                and other["user_id"] == rec["user_id"]
                and other.get("content_hash") == content_hash
            ):
                raise DuplicateKnowledgeFileError(
                    f"duplicate content_hash {content_hash} for user {rec['user_id']}"
                )
        rec["content_hash"] = content_hash
        rec["filename"] = filename
        rec["file_size"] = file_size
        rec["doc_type"] = doc_type
        rec["updated_at"] = datetime.now(UTC)


class SqlKnowledgeFileDAO(KnowledgeFileDAO):
    """MySQL 实现（配置了 mysql 段且 aiomysql 可用时注入）。M2 起使用 AsyncSession。"""

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
            "content_hash": row.content_hash,
            "chunk_count": row.chunk_count,
            "status": row.status,
            "error_message": row.error_message,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "deleted_at": row.deleted_at,
        }

    async def create(
        self,
        user_id: int,
        filename: str,
        file_size: int,
        doc_type: str,
        status: int = 0,
        chunk_count: int = 0,
        error_message: str | None = None,
        content_hash: str = "",
    ) -> dict[str, Any]:
        async with self._db() as db:
            from app.model.knowledge import KnowledgeFile

            row = KnowledgeFile(
                user_id=user_id,
                filename=filename,
                file_size=file_size,
                doc_type=doc_type,
                content_hash=content_hash,
                chunk_count=chunk_count,
                status=status,
                error_message=error_message,
            )
            db.add(row)
            try:
                await db.commit()
            except IntegrityError as exc:
                # (user_id, content_hash) 唯一约束冲突：并发上传同一文件
                await db.rollback()
                raise DuplicateKnowledgeFileError(str(exc)) from exc
            await db.refresh(row)
            return self._to_dict(row)

    async def find_by_content_hash(
        self, user_id: int, content_hash: str
    ) -> dict[str, Any] | None:
        async with self._db() as db:
            from app.model.knowledge import KnowledgeFile

            rows = (
                await db.execute(
                    select(KnowledgeFile)
                    .where(KnowledgeFile.user_id == user_id)
                    .where(KnowledgeFile.content_hash == content_hash)
                    .where(KnowledgeFile.deleted_at.is_(None))
                    .order_by(KnowledgeFile.id.desc())
                )
            ).scalars().all()
            return self._to_dict(rows[0]) if rows else None

    async def list_by_user(self, user_id: int) -> list[dict[str, Any]]:
        async with self._db() as db:
            from app.model.knowledge import KnowledgeFile

            rows = (
                await db.execute(
                    select(KnowledgeFile)
                    .where(KnowledgeFile.user_id == user_id)
                    .where(KnowledgeFile.deleted_at.is_(None))
                    .order_by(KnowledgeFile.id.desc())
                )
            ).scalars().all()
            return [self._to_dict(r) for r in rows]

    async def get_by_id(self, file_id: int) -> dict[str, Any] | None:
        async with self._db() as db:
            from app.model.knowledge import KnowledgeFile

            row = await db.get(KnowledgeFile, file_id)
            if row is None or row.deleted_at is not None:
                return None
            return self._to_dict(row)

    async def update_status(
        self,
        file_id: int,
        status: int,
        chunk_count: int | None = None,
        error_message: str | None = None,
        refresh_created_at: bool = False,
    ) -> None:
        async with self._db() as db:
            from app.model.knowledge import KnowledgeFile

            row = await db.get(KnowledgeFile, file_id)
            if row is None:
                return
            row.status = status
            if chunk_count is not None:
                row.chunk_count = chunk_count
            if error_message is not None:
                row.error_message = error_message
            if refresh_created_at:
                row.created_at = datetime.now(UTC)
            await db.commit()

    async def delete(self, file_id: int) -> None:
        async with self._db() as db:
            from app.model.knowledge import KnowledgeFile

            # 软删除保留哈希槽位：写入「DELETED:{id}」哨兵（非 NULL、按主键全局唯一），
            # 避免 NOT NULL 约束报错，也不会在多文件删除时撞 (user_id, content_hash) 唯一键。
            # 删除后重传相同内容：查重查不到哨兵，自然新建一条记录重新向量化。
            await db.execute(
                update(KnowledgeFile)
                .where(KnowledgeFile.id == file_id)
                .values(deleted_at=datetime.now(UTC), content_hash=f"DELETED:{file_id}")
            )
            await db.commit()

    async def update_content(
        self, file_id: int, content_hash: str, filename: str, file_size: int, doc_type: str
    ) -> None:
        async with self._db() as db:
            from app.model.knowledge import KnowledgeFile

            # 更新内容元信息 + 刷新 updated_at（上传时间）。唯一约束 (user_id, content_hash)
            # 在自身行上保持不变不会冲突；若与他人已上传内容重复，MySQL 抛 IntegrityError。
            try:
                await db.execute(
                    update(KnowledgeFile)
                    .where(KnowledgeFile.id == file_id)
                    .values(
                        content_hash=content_hash,
                        filename=filename,
                        file_size=file_size,
                        doc_type=doc_type,
                        updated_at=datetime.now(UTC),
                    )
                )
                await db.commit()
            except IntegrityError as exc:
                await db.rollback()
                raise DuplicateKnowledgeFileError(str(exc)) from exc
