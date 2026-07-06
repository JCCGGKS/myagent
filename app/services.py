from __future__ import annotations

import json
import re
from pathlib import Path

from app.models import HandoffResult, LogisticsEvent, LogisticsInfo, OrderInfo


DATA_DIR = Path(__file__).resolve().parent / "mock_data"
ORDER_ID_PATTERN = re.compile(r"\b[A-Z]\d{4}\b")


def load_json_file(filename: str) -> list[dict]:
    file_path = DATA_DIR / filename
    with file_path.open("r", encoding="utf-8") as file:
        return json.load(file)


class KnowledgeBaseService:
    def __init__(self) -> None:
        self._faqs = load_json_file("faqs.json")

    def search(self, query: str) -> dict | None:
        normalized = query.casefold()
        best_match = None
        best_score = 0

        for item in self._faqs:
            score = 0
            for keyword in item["keywords"]:
                if keyword.casefold() in normalized:
                    score += 3
            for question in item["questions"]:
                if question.casefold() in normalized:
                    score += 5
            for token in set(normalized.split()):
                if token and token in item["answer"].casefold():
                    score += 1
            if score > best_score:
                best_score = score
                best_match = item

        if best_score < 3:
            return None
        return {"score": best_score, **best_match}


class OrderService:
    def __init__(self) -> None:
        raw_orders = load_json_file("orders.json")
        self._orders = {item["order_id"]: OrderInfo(**item) for item in raw_orders}

    def get_order_status(self, order_id: str) -> OrderInfo | None:
        return self._orders.get(order_id)


class LogisticsService:
    def __init__(self) -> None:
        raw_items = load_json_file("logistics.json")
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
