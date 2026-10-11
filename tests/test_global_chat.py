import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from talkative_backend.backend import chat as chat_backend
from talkative_backend.planes import sqlite_chat_store, sqlite_state_store


class GlobalChatTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        database_path = Path(self.directory.name) / "state.db"
        with patch.object(sqlite_state_store, "STATE_DB", database_path):
            self.state = sqlite_state_store.SQLiteStateStore()
            self.state.init()
        self.app = Flask(__name__)
        self.app.secret_key = "test-session-secret"
        self.app.register_blueprint(chat_backend.chat_bp)
        self.client = self.app.test_client()

    def tearDown(self):
        self.directory.cleanup()

    def test_guest_preview_expires_and_guest_cannot_post(self):
        with patch.object(chat_backend.chat_store, "client", self.state):
            with patch.object(chat_backend, "current_user", return_value=None):
                preview = self.client.get("/api/global-chat")
                self.assertEqual(preview.status_code, 200)
                self.assertFalse(preview.json["authenticated"])
                self.assertFalse(preview.json["preview_expired"])
                self.assertGreater(preview.json["preview_remaining"], 0)

                with self.client.session_transaction() as guest_session:
                    guest_session["global_chat_preview_started_at"] = time.time() - 121

                expired = self.client.get("/api/global-chat")
                self.assertTrue(expired.json["preview_expired"])
                self.assertEqual(expired.json["messages"], [])

                rejected = self.client.post("/api/global-chat", json={"text": "Hello"})
                self.assertEqual(rejected.status_code, 401)

    def test_simulation_feed_is_server_shared_and_incremental(self):
        current_time = chat_backend.GLOBAL_CHAT_SIMULATION_EPOCH + 300
        with patch.object(chat_backend, "GLOBAL_CHAT_SIMULATION_ENABLED", True):
            with patch.object(chat_backend.time, "time", return_value=current_time):
                first = self.client.get("/api/global-chat/simulation")
                second = self.app.test_client().get("/api/global-chat/simulation")
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json, second.json)
            self.assertEqual(len(first.json["messages"]), chat_backend.GLOBAL_CHAT_SIMULATION_HISTORY)

            next_time = current_time + chat_backend.GLOBAL_CHAT_SIMULATION_INTERVAL
            with patch.object(chat_backend.time, "time", return_value=next_time):
                next_message = self.client.get(
                    f"/api/global-chat/simulation?after={first.json['cursor']}"
                )
            self.assertEqual(len(next_message.json["messages"]), 1)
            self.assertEqual(
                next_message.json["messages"][0]["id"],
                first.json["cursor"] + 1,
            )
            self.assertTrue(next_message.json["reset"])

    def test_simulation_feed_requires_flag_and_valid_cursor(self):
        with patch.object(chat_backend, "GLOBAL_CHAT_SIMULATION_ENABLED", False):
            disabled = self.client.get("/api/global-chat/simulation")
        self.assertEqual(disabled.status_code, 404)

        with patch.object(chat_backend, "GLOBAL_CHAT_SIMULATION_ENABLED", True):
            invalid = self.client.get("/api/global-chat/simulation?after=invalid")
        self.assertEqual(invalid.status_code, 400)

    def test_authenticated_messages_are_shared_without_user_ids(self):
        user = {"user_id": "user-1", "first_name": "Avery"}
        with patch.object(chat_backend.chat_store, "client", self.state):
            with patch.object(chat_backend, "current_user", return_value=user):
                with patch.object(chat_backend, "audit"):
                    posted = self.client.post("/api/global-chat", json={"text": "Hello everyone"})
                    self.assertEqual(posted.status_code, 200)

                    loaded = self.client.get("/api/global-chat")
                    self.assertTrue(loaded.json["authenticated"])
                    self.assertEqual(loaded.json["messages"][0]["name"], "Avery")
                    self.assertEqual(loaded.json["messages"][0]["text"], "Hello everyone")
                    self.assertTrue(loaded.json["messages"][0]["mine"])
                    self.assertNotIn("sender_user_id", loaded.json["messages"][0])

    def test_global_message_rate_limit_and_history_cap(self):
        with patch.object(sqlite_chat_store, "client", self.state):
            first = sqlite_chat_store.add_global_chat_message(
                "user-1", "Avery", "First", "2026-10-11T00:00:00+00:00"
            )
            self.assertIsNotNone(first)
            self.assertIsNone(sqlite_chat_store.add_global_chat_message(
                "user-1", "Avery", "Too soon", "2026-10-11T00:00:01+00:00"
            ))
            for index in range(sqlite_chat_store.GLOBAL_CHAT_MAX_MESSAGES + 1):
                sqlite_chat_store.add_global_chat_message(
                    f"batch-{index}",
                    "Name",
                    "Message",
                    "2026-10-11T00:00:00+00:00",
                )
            messages = sqlite_chat_store.global_chat_messages()
            self.assertEqual(len(messages), 50)
            self.assertEqual(self.state.zcard(sqlite_chat_store.GLOBAL_CHAT_MESSAGES_KEY), 500)
            self.assertEqual(messages[-1]["id"], sqlite_chat_store.GLOBAL_CHAT_MAX_MESSAGES + 2)


if __name__ == "__main__":
    unittest.main()
