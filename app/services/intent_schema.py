from __future__ import annotations

from typing import Any


INTENT_SLOT_SCHEMAS: dict[str, dict[str, Any]] = {
    "faq": {
        "required_slots": [],
        "optional_slots": [],
        "inheritable": [],
        "overwritable": [],
        "clarification_order": [],
    },
    "order_service": {
        "required_slots": ["order_id"],
        "optional_slots": [],
        "inheritable": ["order_id"],
        "overwritable": ["order_id"],
        "clarification_order": ["order_id"],
    },
    "logistics_service": {
        "required_slots": ["order_id"],
        "optional_slots": [],
        "inheritable": ["order_id"],
        "overwritable": ["order_id"],
        "clarification_order": ["order_id"],
    },
    "refund_service": {
        "required_slots": ["order_id"],
        "optional_slots": ["refund_reason"],
        "inheritable": ["order_id"],
        "overwritable": ["order_id", "refund_reason"],
        "clarification_order": ["order_id", "refund_reason"],
    },
    "handoff_service": {
        "required_slots": [],
        "optional_slots": [],
        "inheritable": [],
        "overwritable": [],
        "clarification_order": [],
    },
    "chitchat": {
        "required_slots": [],
        "optional_slots": [],
        "inheritable": [],
        "overwritable": [],
        "clarification_order": [],
    },
    "unsupported": {
        "required_slots": [],
        "optional_slots": [],
        "inheritable": [],
        "overwritable": [],
        "clarification_order": [],
    },
}


def get_intent_slot_schema(main_intent: str) -> dict[str, Any]:
    return INTENT_SLOT_SCHEMAS.get(main_intent, INTENT_SLOT_SCHEMAS["unsupported"])
