"""schema 层：Pydantic 请求/响应结构。

按职责拆分为子模块，此处统一再导出，保持 ``from app.schema import X`` 的兼容性：
- ``intent``：意图与情绪（MainIntentCode / SubIntentCode / ActionCode / EmotionState / IntentResult）
- ``session``：会话管理（SessionInitRequest / SessionInitResponse / SessionRenameRequest）
- ``business``：业务领域（OrderInfo / LogisticsEvent / LogisticsInfo / HandoffResult）
- ``state``：会话状态与执行产物（ActionRecord / ToolExecutionResult / ArchivedTaskState / ConversationState）
- ``chat``：对话 I/O（ChatRequest / ChatResponse）
- ``auth``：认证请求/响应（见 auth.py）
"""

from app.schema.business import (
    HandoffResult,
    LogisticsEvent,
    LogisticsInfo,
    OrderInfo,
)
from app.schema.chat import ChatRequest, ChatResponse
from app.schema.intent import (
    ActionCode,
    EmotionState,
    IntentResult,
    MainIntentCode,
    SubIntentCode,
)
from app.schema.session import (
    SessionInitRequest,
    SessionInitResponse,
    SessionRenameRequest,
)
from app.schema.state import (
    ActionRecord,
    ArchivedTaskState,
    ConversationState,
    ToolExecutionResult,
)

__all__ = [
    "ActionCode",
    "ActionRecord",
    "ArchivedTaskState",
    "ChatRequest",
    "ChatResponse",
    "ConversationState",
    "EmotionState",
    "HandoffResult",
    "IntentResult",
    "LogisticsEvent",
    "LogisticsInfo",
    "MainIntentCode",
    "OrderInfo",
    "SessionInitRequest",
    "SessionInitResponse",
    "SessionRenameRequest",
    "SubIntentCode",
    "ToolExecutionResult",
]
