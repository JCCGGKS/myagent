import unittest

from app.rag import KnowledgeBaseService


class RagModuleTestCase(unittest.TestCase):
    def test_knowledge_base_service_should_search_faq_hits(self) -> None:
        service = KnowledgeBaseService()

        hits = service.search("退款多久到账")

        self.assertTrue(hits)
        self.assertEqual(hits[0].doc_type, "faq")
        self.assertIn("工作日", hits[0].answer)


if __name__ == "__main__":
    unittest.main()
