from __future__ import annotations

import re

from app.schema import HandoffResult, LogisticsEvent, LogisticsInfo, OrderInfo
from app.dao.data import load_orders, load_logistics


# 不依赖 \b：Python3 默认 unicode 模式下中文也算「单词字符」，
# 中文与订单号之间没有 \b 边界，会导致「订单A1001」抽取失败。
# 改用显式「非字母数字」前后断言，让中文/标点/空格/字符串边界都成为合法边界。
ORDER_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Z]\d{4}(?![A-Za-z0-9])")


def load_mock_json_file(filename: str) -> list[dict]:
    if filename == "orders.json":
        return load_orders()
    if filename == "logistics.json":
        return load_logistics()
    return []


class OrderService:
    def __init__(self) -> None:
        raw_orders = load_mock_json_file("orders.json")
        self._orders = {item["order_id"]: OrderInfo(**item) for item in raw_orders}

    def get_order_status(self, order_id: str) -> OrderInfo | None:
        return self._orders.get(order_id)


class LogisticsService:
    def __init__(self) -> None:
        raw_items = load_mock_json_file("logistics.json")
        self._records = {}
        for item in raw_items:
            timeline = [LogisticsEvent(**event) for event in item["timeline"]]
            self._records[item["order_id"]] = LogisticsInfo(
                order_id=item["order_id"],
                tracking_status=item["tracking_status"],
                timeline=timeline,
            )

    def get_logistics(self, order_id: str) -> LogisticsInfo | None:
        return self._records.get(order_id)


class HandoffService:
    def __init__(self) -> None:
        self._counter = 1000

    def create_handoff(self, session_id: str, summary: str) -> HandoffResult:
        self._counter += 1
        return HandoffResult(ticket_id=f"H{self._counter}", summary=summary)


def extract_order_id(text: str) -> str | None:
    match = ORDER_ID_PATTERN.search(text.upper())
    return match.group(0) if match else None
