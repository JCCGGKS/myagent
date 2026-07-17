"""schema 层：Pydantic 请求/响应结构。

按职责拆分为子模块，此处统一再导出，保持 ``from app.schema import X`` 的兼容性：
- ``intent``：意图与情绪（MainIntentCode / SubIntentCode / ActionCode / EmotionState / IntentResult）
- ``session``：会话管理（SessionRenameRequest）
- ``business``：业务领域（OrderInfo / LogisticsEvent / LogisticsInfo / HandoffResult）
- ``state``：会话状态与执行产物（ActionRecord / ToolExecutionResult / ConversationState）
- ``chat``：对话 I/O（ChatRequest / ChatResponse）
- ``auth``：认证请求/响应（见 auth.py）
"""

from app.schema.business import (
    HandoffResult,
    LogisticsEvent,
    LogisticsInfo,
    OrderInfo,
    RefundResult,
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
    SessionRenameRequest,
)
from app.schema.state import (
    ActionRecord,
    ConversationState,
    ToolExecutionResult,
)

__all__ = [
    "ActionCode",
    "ActionRecord",
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
    "RefundResult",
    "SessionRenameRequest",
    "SubIntentCode",
    "ToolExecutionResult",
]
