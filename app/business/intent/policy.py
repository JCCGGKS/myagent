"""多轮状态裁决层（DialoguePolicy）。

从 ``StateTrackerService`` 抽离的**覆盖决策**职责：只决定「是否归档旧意图 /
跨意图继承哪些槽位」，不负责把结果写入 ``state``（写入仍由 ``StateTrackerService``
完成，见计划 Phase 2）。单轮分类（规则 + LLM）与多轮裁决由此解耦。
"""

from __future__ import annotations

import logging
from typing import Any

from app.schema import IntentResult
from app.business.intent.schema import IntentSchemaRegistry

logger = logging.getLogger(__name__)


class DialoguePolicy:
    """多轮覆盖决策：意图切换归档、跨意图槽继承。"""

    def __init__(self, schema_registry: IntentSchemaRegistry | None = None) -> None:
        self.schema_registry = schema_registry or IntentSchemaRegistry()

    def should_archive(self, intent: IntentResult, previous_main_intent: str) -> bool:
        """主意图发生切换且上一轮非 unrecognize 时，应归档旧状态。"""
        return intent.is_intent_shift and previous_main_intent != "unrecognize"

    def inherit_slots(
        self, previous_intent: str, next_intent: str, previous_slots: dict[str, str]
    ) -> dict[str, str]:
        """按 YAML ``inheritable`` 计算跨意图可继承槽位（意图继承机制 ②）。

        同一意图（previous == next）时继承其全部已有槽位，实现同意图多轮补槽。
        """
        next_schema = self.schema_registry.get(next_intent)
        inheritable = set(next_schema.get("inheritable", []))
        if previous_intent == next_intent:
            inheritable |= set(previous_slots.keys())
        return {key: value for key, value in previous_slots.items() if key in inheritable}
