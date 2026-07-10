import unittest

from app.schema import ConversationState
from app.business.context import ContextService
from app.business.intent.routing import StateTrackerService


class ContextServicesTestCase(unittest.TestCase):
    def test_context_service_should_keep_recent_window_and_append_running_summary(self) -> None:
        service = ContextService(state_tracker=StateTrackerService(), max_recent_messages=4)
        state = ConversationState(session_id="s1", user_id=1, channel="web", reply="本轮回复")
        state.recent_messages = [
            {"role": "user", "content": "m1"},
            {"role": "assistant", "content": "m2"},
            {"role": "user", "content": "m3"},
            {"role": "assistant", "content": "m4"},
        ]

        updated = service.compress(state)

        self.assertEqual(len(updated.recent_messages), 4)
        self.assertTrue(updated.running_summary)
        self.assertEqual(updated.recent_messages[-1]["content"], "本轮回复")
        self.assertIn("user:m1", updated.running_summary)


if __name__ == "__main__":
    unittest.main()
