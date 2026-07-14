"""R1 二次确认的「确认/取消」信号识别。

挂在 ``ConversationState.pending_confirmation`` 上的待确认操作，需要用户下一轮用
自然语言回复「确认」或「取消」。该判定必须是**确定性的**，不能依赖 LLM 自由函数调用
去回忆「上一轮我是不是问过确认」——否则会出现「用户回了确认、系统却当新意图处理」
的失效（见 06_工具调用 回归）。

设计要点：
- 仅在 ``pending_confirmation`` 非空时由 guard 节点调用，故偶发误判不影响正常对话；
- 先精确匹配常见短回复，再用关键词子串兜底（覆盖「确认，继续」「我要确认」等）；
- 取消词优先于确认词（避免「不确认」误判为确认）。
"""

from __future__ import annotations

from typing import Literal

ConfirmSignal = Literal["confirm", "cancel", None]

# 精确匹配（消息去除首尾空白、casefold 后）
_CONFIRM_EXACT = {
    "确认", "确定", "同意", "继续", "是", "执行", "提交",
    "好的", "好", "没问题", "OK".lower(), "yes", "y",
}
_CANCEL_EXACT = {
    "取消", "不了", "算了", "放弃", "暂不", "别退了", "不退款了",
    "no", "n",
}

# 子串兜底关键词
_CANCEL_SUBSTR = ("取消", "别退", "不退款", "算了", "放弃", "不用退")
_CONFIRM_SUBSTR = ("确认", "确定", "同意")


def classify_confirm_signal(text: str) -> ConfirmSignal:
    """识别用户回复是确认 / 取消 / 无关。

    - ``"confirm"``：用户确认执行挂起操作；
    - ``"cancel"``：用户取消挂起操作；
    - ``None``：既非确认也非取消（用户可能转移了话题）。
    """
    if not text:
        return None
    t = text.strip().casefold()

    if t in _CANCEL_EXACT:
        return "cancel"
    if t in _CONFIRM_EXACT:
        return "confirm"

    # 子串兜底（取消优先）：含取消子串，或「否定词 + 确认词」（如「不确认」「不想确认」）
    # 视为取消，避免否定句式被「确认」子串误判为确认。
    if any(k in t for k in _CANCEL_SUBSTR):
        return "cancel"
    if any(t.startswith(neg) and conf in t for neg in ("不", "别", "不用", "暂") for conf in _CONFIRM_SUBSTR):
        return "cancel"
    if any(k in t for k in _CONFIRM_SUBSTR):
        return "confirm"
    return None
