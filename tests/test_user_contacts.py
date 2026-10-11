import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from talkative_backend.backend import chat as chat_backend
from talkative_backend.planes import sqlite_chat_store, sqlite_state_store, user_store


class UserContactsTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_patches = [
            patch.object(user_store, "USER_DB", Path(self.temp_directory.name) / "users.db"),
            patch.object(user_store, "LEGACY_DB", Path(self.temp_directory.name) / "missing-legacy.db"),
        ]
        for patcher in self.database_patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.temp_directory.cleanup)
        user_store.init()

    def create_user(self, index):
        return user_store.create_user(
            f"person{index}@example.com",
            f"person{index}",
            "password-hash",
            f"Person{index}",
            "Test",
            "1990-01-01",
            "prefer_not_to_say",
            "IN",
            "2026-01-01T00:00:00+00:00",
            "v1",
            "2026-01-01T00:00:00+00:00",
        )

    def test_contact_pair_capacity_is_symmetric_and_does_not_partially_add(self):
        users = [self.create_user(index) for index in range(12)]
        owner, *peers = users
        for peer in peers[:user_store.CONTACT_LIMIT]:
            result, conversation_id = user_store.add_contact_pair(
                owner, peer, "2026-01-01T00:00:00+00:00"
            )
            self.assertEqual(result, "connected")
            self.assertTrue(conversation_id.startswith("ct_"))
            self.assertEqual(
                user_store.contact_peer(owner, conversation_id), peer
            )
            self.assertEqual(
                user_store.contact_peer(peer, conversation_id), owner
            )

        result, conversation_id = user_store.add_contact_pair(
            owner, peers[-1], "2026-01-01T00:00:00+00:00"
        )

        self.assertEqual((result, conversation_id), ("full", None))
        self.assertEqual(len(user_store.list_contacts(owner)), user_store.CONTACT_LIMIT)
        self.assertEqual(user_store.list_contacts(peers[-1]), [])

    def test_messages_are_shared_only_by_contacts_and_removed_with_connection(self):
        first, second, outsider = (self.create_user(index) for index in range(3))
        _, conversation_id = user_store.add_contact_pair(
            first, second, "2026-01-01T00:00:00+00:00"
        )
        self.assertEqual(user_store.contact_message_history(first, conversation_id), [])
        self.assertTrue(user_store.add_contact_message(
            first, conversation_id, "Hello", "2026-01-01T00:00:00+00:00"
        ))

        self.assertEqual(
            user_store.contact_message_history(first, conversation_id)[0]["mine"],
            True,
        )
        peer_messages = user_store.contact_message_history(second, conversation_id)
        self.assertEqual(peer_messages[0]["text"], "Hello")
        self.assertFalse(peer_messages[0]["mine"])
        self.assertIsNone(user_store.contact_message_history(outsider, conversation_id))

        self.assertEqual(
            user_store.contact_message_history(first, conversation_id, after=0)[0]["id"],
            1,
        )
        self.assertTrue(user_store.remove_contact(first, conversation_id))
        self.assertEqual(user_store.list_contacts(first), [])
        self.assertEqual(user_store.list_contacts(second), [])
        self.assertIsNone(user_store.contact_message_history(first, conversation_id))

    def test_blocking_removes_contact_messages(self):
        first, second = (self.create_user(index) for index in range(2))
        _, conversation_id = user_store.add_contact_pair(
            first, second, "2026-01-01T00:00:00+00:00"
        )
        user_store.add_contact_message(
            second, conversation_id, "Hello", "2026-01-01T00:00:00+00:00"
        )

        user_store.block_pair(first, second, "2026-01-02T00:00:00+00:00")

        self.assertEqual(user_store.list_contacts(first), [])
        self.assertEqual(user_store.list_contacts(second), [])
        self.assertIsNone(user_store.contact_message_history(first, conversation_id))


class StayInTouchConsentTests(unittest.TestCase):
    def test_both_participants_must_agree_while_chat_is_active(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "state.db"
            with patch.object(sqlite_state_store, "STATE_DB", database_path):
                state = sqlite_state_store.SQLiteStateStore()
                state.init()
                with patch.object(sqlite_chat_store, "client", state):
                    started_at = datetime.now(timezone.utc).isoformat()
                    sqlite_chat_store.match_or_queue("user-a", lambda *_: False, started_at)
                    _, session_id, _ = sqlite_chat_store.match_or_queue(
                        "user-b", lambda *_: False, started_at
                    )

                    first_choice = sqlite_chat_store.agree_stay_in_touch(
                        session_id, "user-a"
                    )
                    self.assertTrue(first_choice["by_me"])
                    self.assertFalse(first_choice["by_peer"])
                    self.assertFalse(
                        sqlite_chat_store.read_messages(session_id, "user-b", 0)[
                            "stay_in_touch_by_me"
                        ]
                    )
                    self.assertTrue(
                        sqlite_chat_store.read_messages(session_id, "user-b", 0)[
                            "stay_in_touch_by_peer"
                        ]
                    )

                    second_choice = sqlite_chat_store.agree_stay_in_touch(
                        session_id, "user-b"
                    )
                    self.assertTrue(second_choice["by_me"])
                    self.assertTrue(second_choice["by_peer"])

                    sqlite_chat_store.end_session(
                        session_id, "user-a", datetime.now(timezone.utc).isoformat()
                    )
                    self.assertIsNone(
                        sqlite_chat_store.agree_stay_in_touch(session_id, "user-b")
                    )

                    sqlite_chat_store.match_or_queue("user-c", lambda *_: False, started_at)
                    _, declined_session_id, _ = sqlite_chat_store.match_or_queue(
                        "user-d", lambda *_: False, started_at
                    )
                    sqlite_chat_store.agree_stay_in_touch(declined_session_id, "user-c")
                    declined = sqlite_chat_store.decline_stay_in_touch(
                        declined_session_id, "user-d"
                    )
                    self.assertEqual(declined["result"], "declined")
                    unchanged = sqlite_chat_store.agree_stay_in_touch(
                        declined_session_id, "user-c"
                    )
                    self.assertEqual(unchanged["result"], "declined")
                    self.assertEqual(
                        sqlite_chat_store.read_messages(declined_session_id, "user-c", 0)[
                            "stay_in_touch_result"
                        ],
                        "declined",
                    )


class StayInTouchApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.user_database_patches = [
            patch.object(user_store, "USER_DB", Path(self.temp_directory.name) / "users.db"),
            patch.object(user_store, "LEGACY_DB", Path(self.temp_directory.name) / "missing-legacy.db"),
        ]
        for patcher in self.user_database_patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        state_path_patcher = patch.object(
            sqlite_state_store, "STATE_DB", Path(self.temp_directory.name) / "state.db"
        )
        state_path_patcher.start()
        self.addCleanup(state_path_patcher.stop)
        self.addCleanup(self.temp_directory.cleanup)
        user_store.init()
        self.state = sqlite_state_store.SQLiteStateStore()
        self.state.init()
        self.state_patcher = patch.object(sqlite_chat_store, "client", self.state)
        self.state_patcher.start()
        self.addCleanup(self.state_patcher.stop)
        self.audit_patcher = patch.object(chat_backend, "audit")
        self.audit_patcher.start()
        self.addCleanup(self.audit_patcher.stop)

        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.app.register_blueprint(chat_backend.chat_bp)
        self.client = self.app.test_client()
        self.first = self.create_user(20)
        self.second = self.create_user(21)
        started_at = datetime.now(timezone.utc).isoformat()
        sqlite_chat_store.match_or_queue(self.first, lambda *_: False, started_at)
        _, self.session_id, _ = sqlite_chat_store.match_or_queue(
            self.second, lambda *_: False, started_at
        )

    def create_user(self, index):
        return user_store.create_user(
            f"person{index}@example.com",
            f"person{index}",
            "password-hash",
            f"Person{index}",
            "Test",
            "1990-01-01",
            "prefer_not_to_say",
            "IN",
            "2026-01-01T00:00:00+00:00",
            "v1",
            "2026-01-01T00:00:00+00:00",
        )

    def login_as(self, user_id):
        with self.client.session_transaction() as session:
            session["role"] = "user"
            session["user_id"] = user_id

    def test_participant_can_decline_peer_stay_in_touch_request(self):
        self.login_as(self.first)
        accepted = self.client.post(
            f"/api/stay-in-touch/{self.session_id}", json={"action": "accept"}
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertFalse(accepted.json["agreed_by_peer"])

        self.login_as(self.second)
        declined = self.client.post(
            f"/api/stay-in-touch/{self.session_id}", json={"action": "decline"}
        )
        self.assertEqual(declined.status_code, 200)
        self.assertEqual(declined.json["result"], "declined")
        self.assertEqual(user_store.list_contacts(self.first), [])
        state = sqlite_chat_store.read_messages(self.session_id, self.first, 0)
        self.assertEqual(state["stay_in_touch_result"], "declined")

    def test_contacts_api_returns_chat_peer_details_without_private_identity(self):
        _, conversation_id = user_store.add_contact_pair(
            self.first, self.second, datetime.now(timezone.utc).isoformat()
        )
        user_store.add_contact_message(
            self.second, conversation_id, "Hello", datetime.now(timezone.utc).isoformat()
        )
        self.login_as(self.first)

        response = self.client.get("/api/contacts")

        self.assertEqual(response.status_code, 200)
        contact = response.json["contacts"][0]
        self.assertEqual(contact["conversation_id"], conversation_id)
        self.assertEqual(contact["peer"]["name"], "Person21")
        self.assertTrue(contact["peer"]["age_category"])
        self.assertFalse(contact["last_message_mine"])
        self.assertNotIn("user_id", contact["peer"])
        self.assertNotIn("email", contact["peer"])

    def test_contact_typing_and_peer_presence_are_contact_scoped(self):
        _, conversation_id = user_store.add_contact_pair(
            self.first, self.second, datetime.now(timezone.utc).isoformat()
        )
        sqlite_chat_store.touch_presence(self.second)
        self.login_as(self.second)
        typing_response = self.client.post(f"/api/contact-typing/{conversation_id}")
        self.assertEqual(typing_response.status_code, 200)

        self.login_as(self.first)
        messages_response = self.client.get(f"/api/contact-messages/{conversation_id}")
        self.assertEqual(messages_response.status_code, 200)
        self.assertTrue(messages_response.json["typing"])
        self.assertTrue(messages_response.json["peer_presence"]["online"])

        self.login_as(self.create_user(22))
        forbidden_typing = self.client.post(f"/api/contact-typing/{conversation_id}")
        self.assertEqual(forbidden_typing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
