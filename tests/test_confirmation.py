"""R1 二次确认的「确认/取消」信号识别单测。"""

import pytest

from app.business.tools.confirmation import classify_confirm_signal


class TestClassifyConfirmSignal:
    @pytest.mark.parametrize(
        "text",
        ["确认", "确定", "同意", "继续", "是", "执行", "提交", "好的", "没问题", "yes", "y", "OK", "确认，继续吧"],
    )
    def test_confirm_signals(self, text):
        assert classify_confirm_signal(text) == "confirm"

    @pytest.mark.parametrize(
        "text",
        ["取消", "不了", "算了", "放弃", "暂不", "别退了", "不退款了", "no", "n", "我要取消"],
    )
    def test_cancel_signals(self, text):
        assert classify_confirm_signal(text) == "cancel"

    @pytest.mark.parametrize(
        "text",
        ["", "退款", "我想退款", "A1002", "在吗", "你好"],
    )
    def test_neither(self, text):
        assert classify_confirm_signal(text) is None

    def test_cancel_priority_over_confirm(self):
        # 「不确认」应判为取消而非确认（取消词优先）
        assert classify_confirm_signal("不确认") == "cancel"
