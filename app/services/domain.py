from __future__ import annotations

import re
from pathlib import Path

from app.models import HandoffResult, KnowledgeHit, LogisticsEvent, LogisticsInfo, OrderInfo
from app.utils import load_json_file


DATA_DIR = Path(__file__).resolve().parents[1] / "mock_data"
ORDER_ID_PATTERN = re.compile(r"\b[A-Z]\d{4}\b")


def load_mock_json_file(filename: str) -> list[dict]:
    return load_json_file(DATA_DIR / filename)


class KnowledgeBaseService:
    def __init__(self) -> None:
        self._faqs = load_mock_json_file("faqs.json")

    def search(self, query: str) -> list[KnowledgeHit]:
        normalized = query.casefold()
        hits: list[KnowledgeHit] = []

        for item in self._faqs:
            best_score = 0.0
            best_question = ""

            for question in item["questions"]:
                question_normalized = question.casefold()
                if question_normalized in normalized or normalized in question_normalized:
                    best_score = max(best_score, 1.0)
                    best_question = question

            keyword_hits = 0
            for keyword in item["keywords"]:
                if keyword.casefold() in normalized:
                    keyword_hits += 1

            if keyword_hits:
                score = min(0.4 + keyword_hits * 0.25, 0.95)
                if score > best_score:
                    best_score = score
                    best_question = item["questions"][0]

            if best_score > 0:
                faq_key = item["questions"][0]
                hits.append(
                    KnowledgeHit(
                        faq_key=faq_key,
                        question=best_question or item["questions"][0],
                        answer=item["answer"],
                        score=best_score,
                        doc_type="faq",
                    )
                )

        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:3]


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
