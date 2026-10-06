import unittest
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from talkative_backend.config import STATE_DB
from talkative_backend.planes import sqlite_chat_store, sqlite_state_store


class ChatLifecycleTests(unittest.TestCase):
    def test_init_creates_state_tables_before_health_check(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "state.db"
            with patch.object(sqlite_state_store, "STATE_DB", database_path):
                state = sqlite_state_store.SQLiteStateStore()
                with patch.object(sqlite_chat_store, "client", state):
                    sqlite_chat_store.init()
                self.assertEqual(state.incr("signup-rate-limit"), 1)

    def test_match_message_typing_leave_and_end_use_persistent_state(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "state.db"
            with patch.object(sqlite_state_store, "STATE_DB", database_path):
                state = sqlite_state_store.SQLiteStateStore()
                state.init()
                with patch.object(sqlite_chat_store, "client", state):
                    started_at = datetime.now(timezone.utc).isoformat()
                    match = sqlite_chat_store.match_or_queue("user-a", lambda *_: False, started_at)
                    self.assertEqual(match, ("waiting", None, None))

                    match = sqlite_chat_store.match_or_queue("user-b", lambda *_: False, started_at)
                    self.assertEqual(match[0], "matched")
                    session_id = match[1]

                    self.assertTrue(sqlite_chat_store.add_message(session_id, "user-a", "hello", started_at))
                    self.assertTrue(sqlite_chat_store.set_typing(session_id, "user-a", started_at))
                    messages = sqlite_chat_store.read_messages(session_id, "user-b", 0)
                    self.assertEqual(messages["messages"], [{"id": 1, "text": "hello", "mine": False}])
                    self.assertTrue(messages["typing"])

                    self.assertTrue(sqlite_chat_store.begin_leave(session_id, "user-a"))
                    self.assertFalse(sqlite_chat_store.add_message(session_id, "user-a", "blocked", started_at))
                    self.assertTrue(sqlite_chat_store.cancel_leave(session_id, "user-a"))

                    ended_at = datetime.now(timezone.utc).isoformat()
                    ended = sqlite_chat_store.end_session(session_id, "user-a", ended_at)
                    self.assertEqual([message["text"] for message in ended["transcript"]], ["hello"])
                    self.assertFalse(sqlite_chat_store.add_message(session_id, "user-a", "too late", ended_at))
                    self.assertIsNone(sqlite_chat_store.begin_leave(session_id, "user-a"))
                    self.assertTrue(sqlite_chat_store.read_messages(session_id, "user-b", 0)["ended"])

    def test_cleanup_does_not_remove_a_newer_user_session(self):
        ended_session = "dm-ended"
        new_session = "dm-new"
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "state.db"
            with patch.object(sqlite_state_store, "STATE_DB", database_path):
                state = sqlite_state_store.SQLiteStateStore()
                state.init()
                user_a_key = f"{sqlite_chat_store.PREFIX}user-session:user-a"
                user_b_key = f"{sqlite_chat_store.PREFIX}user-session:user-b"
                state.hset(f"{sqlite_chat_store.PREFIX}session:{ended_session}", mapping={
                    "ended_at": "2026-10-04T00:00:00+00:00",
                    "user_a": "user-a",
                    "user_b": "user-b",
                })
                state.set(user_a_key, new_session)
                state.set(user_b_key, ended_session)
                with patch.object(sqlite_chat_store, "client", state):
                    sqlite_chat_store.cleanup_ended(ended_session)
                self.assertEqual(state.get(user_a_key), new_session)
                self.assertEqual(state.get(user_b_key), None)


if __name__ == "__main__":
    unittest.main()
