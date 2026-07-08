from __future__ import annotations

from pathlib import Path

from app.models import KnowledgeHit
from app.utils import load_json_file


DATA_DIR = Path(__file__).resolve().parents[1] / "mock_data"


def load_rag_json_file(filename: str) -> list[dict]:
    return load_json_file(DATA_DIR / filename)


class KnowledgeBaseService:
    def __init__(self) -> None:
        self._faqs = load_rag_json_file("rag.json")

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
