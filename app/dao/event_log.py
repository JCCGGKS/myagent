from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy import select

from app.model import AsyncSessionLocal
from app.model.session import EventLog

logger = logging.getLogger(__name__)


class EventLogStore(ABC):
    """事件流存储接口（dao 层）。业务层只依赖此接口，实现可注入。"""

    @abstractmethod
    async def append_event(
        self,
        session_id: str,
        trace_id: str,
        event_type: str,
        node: str | None,
        payload: dict[str, Any],
        turn: int = 0,
    ) -> None:
        ...

    @abstractmethod
    async def get_events(
        self, session_id: str, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        """按 session_id（可选 trace_id）拉回事件，按时间正序，便于回放决策链。"""


class MemoryEventLogStore(EventLogStore):
    """内存实现（本地/测试默认）。"""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    async def append_event(
        self,
        session_id: str,
        trace_id: str,
        event_type: str,
        node: str | None,
        payload: dict[str, Any],
        turn: int = 0,
    ) -> None:
        self._events.append(
            {
                "session_id": session_id,
                "trace_id": trace_id,
                "turn": turn,
                "event_type": event_type,
                "node": node,
                "payload": payload,
            }
        )

    async def get_events(
        self, session_id: str, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        result = [
            e
            for e in self._events
            if e["session_id"] == session_id and (trace_id is None or e["trace_id"] == trace_id)
        ]
        return [e["payload"] for e in result]


class SqlEventLogStore(EventLogStore):
    """MySQL 实现（配置了 mysql 段且 aiomysql 可用时注入）。"""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def _db(self):
        return self._session_factory()

    async def append_event(
        self,
        session_id: str,
        trace_id: str,
        event_type: str,
        node: str | None,
        payload: dict[str, Any],
        turn: int = 0,
    ) -> None:
        async with self._db() as db:
            db.add(
                EventLog(
                    session_id=session_id,
                    trace_id=trace_id,
                    turn=turn,
                    event_type=event_type,
                    node=node,
                    payload=json.dumps(payload, ensure_ascii=False),
                )
            )
            await db.commit()

    async def get_events(
        self, session_id: str, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        async with self._db() as db:
            stmt = select(EventLog).where(EventLog.session_id == session_id)
            if trace_id is not None:
                stmt = stmt.where(EventLog.trace_id == trace_id)
            stmt = stmt.order_by(EventLog.id.asc())
            rows = (await db.execute(stmt)).scalars().all()
            return [json.loads(r.payload) for r in rows]


def get_event_log_store() -> EventLogStore:
    """根据是否配置 mysql（异步 engine 可用）选择实现：有异步 engine 用 Sql，否则内存。"""
    if AsyncSessionLocal is not None:
        return SqlEventLogStore(AsyncSessionLocal)
    return MemoryEventLogStore()
