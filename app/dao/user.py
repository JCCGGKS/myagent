from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class UserDAO(ABC):
    """用户数据访问接口（dao 层）。认证业务只依赖此接口。"""

    @abstractmethod
    def get_by_username(self, username: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    def get_by_email(self, email: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    def get_by_id(self, user_id: int) -> dict[str, Any] | None:
        ...

    @abstractmethod
    def create(self, username: str, email: str, password_hash: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def update_password(self, user_id: int, password_hash: str) -> None:
        ...


class MemoryUserDAO(UserDAO):
    """内存实现（本地/测试默认）。"""

    def __init__(self) -> None:
        self._by_id: dict[int, dict[str, Any]] = {}
        self._by_username: dict[str, int] = {}
        self._by_email: dict[str, int] = {}
        self._seq: int = 0

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        uid = self._by_username.get(username)
        return dict(self._by_id[uid]) if uid is not None else None

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        uid = self._by_email.get(email)
        return dict(self._by_id[uid]) if uid is not None else None

    def get_by_id(self, user_id: int) -> dict[str, Any] | None:
        user = self._by_id.get(user_id)
        return dict(user) if user is not None else None

    def create(self, username: str, email: str, password_hash: str) -> dict[str, Any]:
        self._seq += 1
        user_id = self._seq
        user = {
            "id": user_id,
            "username": username,
            "email": email,
            "password_hash": password_hash,
        }
        self._by_id[user_id] = user
        self._by_username[username] = user_id
        self._by_email[email] = user_id
        return dict(user)

    def update_password(self, user_id: int, password_hash: str) -> None:
        user = self._by_id.get(user_id)
        if user is not None:
            user["password_hash"] = password_hash


class SqlUserDAO(UserDAO):
    """MySQL 实现（配置了 mysql 段时注入）。"""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def _db(self):
        return self._session_factory()

    @staticmethod
    def _to_dict(user: Any) -> dict[str, Any]:
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "password_hash": user.password_hash,
        }

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        with self._db() as db:
            from app.model.user import User

            user = db.query(User).filter(User.username == username).first()
            return self._to_dict(user) if user else None

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        with self._db() as db:
            from app.model.user import User

            user = db.query(User).filter(User.email == email).first()
            return self._to_dict(user) if user else None

    def get_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self._db() as db:
            from app.model.user import User

            user = db.get(User, user_id)
            return self._to_dict(user) if user else None

    def create(self, username: str, email: str, password_hash: str) -> dict[str, Any]:
        with self._db() as db:
            from app.model.user import User

            user = User(username=username, email=email, password_hash=password_hash)
            db.add(user)
            db.commit()
            db.refresh(user)
            return self._to_dict(user)

    def update_password(self, user_id: int, password_hash: str) -> None:
        with self._db() as db:
            from app.model.user import User

            user = db.get(User, user_id)
            if user is None:
                return
            user.password_hash = password_hash
            db.commit()
