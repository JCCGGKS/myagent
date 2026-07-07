import unittest

from app.models import ConversationState
from app.rag import KnowledgeBaseService, RagRetrievalService


class RagModuleTestCase(unittest.TestCase):
    def test_knowledge_base_service_should_search_faq_hits(self) -> None:
        service = KnowledgeBaseService()

        hits = service.search("退款多久到账")

        self.assertTrue(hits)
        self.assertEqual(hits[0].doc_type, "faq")
        self.assertIn("工作日", hits[0].answer)

    def test_rag_retrieval_service_should_write_knowledge_tool_result(self) -> None:
        service = RagRetrievalService(knowledge_base=KnowledgeBaseService())
        state = ConversationState(session_id="s2", user_id="u1", channel="web", last_user_message="退款多久到账")

        updated = service.retrieve(state)

        self.assertEqual(updated.tool_result.kind, "knowledge")
        self.assertEqual(updated.latest_action_name, "knowledge_retriever")
        self.assertIn("工作日", updated.tool_result.user_facing_summary)


if __name__ == "__main__":
    unittest.main()
