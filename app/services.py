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
        best_score = 0.0

        for item in self._faqs:
            score = 0.0

            for keyword in item["keywords"]:
                keyword_normalized = keyword.casefold()
                if keyword_normalized in normalized:
                    if len(keyword_normalized) >= 3:
                        score += 3.0
                    else:
                        score += 1.0

            for question in item["questions"]:
                question_normalized = question.casefold()
                if question_normalized in normalized or normalized in question_normalized:
                    score += 5.0
                else:
                    score += self._question_similarity(normalized, question_normalized) * 2.0

            if score > best_score:
                best_score = score
                best_match = item

        if best_match is None:
            return None

        if best_score < 3.5:
            return None

        if not self._has_strong_match(normalized, best_match):
            return None

        return {"score": round(best_score, 3), **best_match}

    def _has_strong_match(self, query: str, item: dict) -> bool:
        for keyword in item["keywords"]:
            keyword_normalized = keyword.casefold()
            if len(keyword_normalized) >= 3 and keyword_normalized in query:
                return True

        for question in item["questions"]:
            question_normalized = question.casefold()
            if question_normalized in query or query in question_normalized:
                return True
            if self._question_similarity(query, question_normalized) >= 0.65:
                return True

        return False

    def _question_similarity(self, query: str, question: str) -> float:
        query_bigrams = self._bigrams(query)
        question_bigrams = self._bigrams(question)
        if not query_bigrams or not question_bigrams:
            return 0.0

        overlap = len(query_bigrams & question_bigrams)
        union = len(query_bigrams | question_bigrams)
        return overlap / union if union else 0.0

    def _bigrams(self, text: str) -> set[str]:
        compact = re.sub(r"\s+", "", text)
        if len(compact) < 2:
            return {compact} if compact else set()
        return {compact[index : index + 2] for index in range(len(compact) - 1)}


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
