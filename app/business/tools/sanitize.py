"""工具结果脱敏：跨信任边界前，对 PII 字段做必要掩码。

决策层（工具 handler）产出的 ``raw_result`` 含全量业务数据，可能带有手机号、身份证、
地址、姓名、邮箱等敏感字段。在把结果交给 LLM 观测 / 事件流 / 用户回复之前，需统一生成
``sanitized_result``（脱敏副本），**绝不直接等于 ``raw_result``**——只有命中敏感字段的
才掩码，其余原样透传。

实现采用「字段名启发式 + 正则」的纯规则方案（不调 LLM，确定性强、零成本、可单测）。
"""

from __future__ import annotations

import re
from typing import Any

# 手机号：1 开头、11 位数字
PHONE_RE = re.compile(r"^1\d{10}$")
# 身份证：15 位或 18 位（末位可为 X）
ID_RE = re.compile(r"^\d{15}(\d{2}[\dXx])?$")

_MASK = "****"


def _mask_middle(value: str, keep_prefix: int, keep_suffix: int) -> str:
    """保留前 ``keep_prefix``、后 ``keep_suffix`` 个字符，中间以 **** 替换。

    字符串过短（两端保留长度之和超过总长）时直接全掩，避免泄露。
    """
    if len(value) <= keep_prefix + keep_suffix:
        return _MASK
    head = value[:keep_prefix]
    tail = value[-keep_suffix:] if keep_suffix else ""
    return f"{head}{_MASK}{tail}"


def _sanitize_value(key: str, value: Any) -> Any:
    """按字段名启发式 + 正则判定敏感类型，对非敏感字段原样透传。"""
    if not isinstance(value, str):
        return value
    low = key.lower()
    if low in {"phone", "mobile", "tel"} or PHONE_RE.fullmatch(value):
        return _mask_middle(value, 3, 4)  # 手机号：保留前3后4
    if low in {"id_card", "idcard", "identity"} or ID_RE.fullmatch(value):
        return _mask_middle(value, 0, 4)  # 身份证：仅留后4位
    if low in {"address", "new_address", "recv_address"}:
        return _mask_middle(value, 6, 2)  # 地址：保留前6后2
    if low in {"name", "contact_name", "receiver"}:
        return _mask_middle(value, 1, 0)  # 姓名：保留姓氏
    if low in {"email", "mail"}:
        local, _, domain = value.partition("@")
        return f"{_mask_middle(local, 1, 1)}@{domain}"  # 邮箱：本地部分掩中间，留域名
    return value


def sanitize_tool_result(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """对工具原始结果做必要脱敏，返回脱敏副本（与 ``raw`` 非同一对象）。

    - ``raw`` 为空（``None`` / 空 dict）→ 原样返回，不强行造空壳；
    - 否则逐字段过 :func:`_sanitize_value`，仅敏感字段被掩码。
    """
    if not raw:
        return raw
    return {k: _sanitize_value(k, v) for k, v in raw.items()}
