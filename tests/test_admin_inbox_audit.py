import sqlite3
import tempfile
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from talkative_backend.backend import admin
from talkative_backend import email_inbox
from talkative_backend.email_inbox import _text_body
from talkative_backend.planes import admin_store


class AdminInboxAuditTests(unittest.TestCase):
    def test_inbox_routes_require_admin(self):
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.register_blueprint(admin.admin_bp)
        client = app.test_client()
        with patch.object(admin, "admin_authorized", return_value=False), patch.object(
            admin, "list_messages"
        ) as list_messages:
            response = client.get("/admin/api/inbox")
        self.assertEqual(response.status_code, 401)
        list_messages.assert_not_called()

    def test_admin_can_read_mailbox_message_without_marking_it_read(self):
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.register_blueprint(admin.admin_bp)
        client = app.test_client()
        with client.session_transaction() as user_session:
            user_session.update(role="admin", admin_username="operator")

        message = {
            "uid": "42",
            "date": "Tue, 07 Oct 2026 08:00:00 +0000",
            "from": "visitor@example.com",
            "to": "support@example.com",
            "subject": "Help",
            "body": "Please help me.",
        }
        with patch.object(admin, "admin_authorized", return_value=True), patch.object(
            admin, "read_message", return_value=message
        ) as read_message, patch.object(admin, "audit") as audit:
            response = client.get("/admin/api/inbox/42")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, message)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        read_message.assert_called_once_with("42")
        audit.assert_called_once_with("admin_inbox_message_viewed")

    def test_html_mail_is_exposed_as_text_only(self):
        message = BytesParser(policy=policy.default).parsebytes(
            b"From: sender@example.com\n"
            b"Content-Type: text/html; charset=utf-8\n\n"
            b"<p>Hello <strong>Talkative</strong></p><script>alert(1)</script>"
        )
        self.assertEqual(_text_body(message), "Hello Talkative alert(1)")

    @patch.object(email_inbox, "IMAP_HOST", "imap.example.com")
    @patch.object(email_inbox, "IMAP_PORT", 993)
    @patch.object(email_inbox, "SMTP_USERNAME", "support@example.com")
    @patch.object(email_inbox, "SMTP_PASSWORD", "mailbox-password")
    @patch.object(email_inbox.imaplib, "IMAP4_SSL")
    def test_inbox_reads_recent_headers_without_changing_mailbox(self, imap_class):
        client = imap_class.return_value
        client.select.return_value = ("OK", [b"2"])
        client.uid.side_effect = [
            ("OK", [b"1 2"]),
            (
                "OK",
                [
                    (
                        b"2 (RFC822.SIZE 30 FLAGS (\\Seen))",
                        b"From: second@example.com\nSubject: Second\n\n",
                    )
                ],
            ),
            (
                "OK",
                [
                    (
                        b"1 (RFC822.SIZE 20 FLAGS ())",
                        b"From: first@example.com\nSubject: First\n\n",
                    )
                ],
            ),
        ]

        result = email_inbox.list_messages()

        self.assertEqual([item["uid"] for item in result["messages"]], ["2", "1"])
        self.assertTrue(result["messages"][0]["is_read"])
        self.assertFalse(result["messages"][1]["is_read"])
        client.select.assert_called_once_with("INBOX", readonly=True)
        client.store.assert_not_called()
        client.logout.assert_called_once()

    def test_activity_logs_identify_user_and_admin_actor(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(admin_store, "ADMIN_DB", Path(directory) / "admin.db"):
                admin_store.init()
                admin_store.record_event(
                    "login_succeeded", "usr_1", actor_role="user", actor_id="usr_1"
                )
                admin_store.record_event(
                    "admin_user_blocked",
                    "usr_1",
                    actor_role="admin",
                    actor_id="operator",
                )

                events = admin_store.activity_log()
                by_event = {event["event"]: event for event in events}
                user_activity = admin_store.user_activity("usr_1")

        self.assertEqual(by_event["login_succeeded"]["actor_role"], "user")
        self.assertEqual(by_event["login_succeeded"]["actor_id"], "usr_1")
        self.assertEqual(by_event["admin_user_blocked"]["actor_role"], "admin")
        self.assertEqual(by_event["admin_user_blocked"]["actor_id"], "operator")
        self.assertEqual(len(user_activity), 2)
        self.assertEqual(
            next(item for item in user_activity if item["event"] == "admin_user_blocked")["actor_id"],
            "operator",
        )

    def test_activity_schema_upgrades_existing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "admin.db"
            with sqlite3.connect(database_path) as db:
                db.execute(
                    "CREATE TABLE accounting(id INTEGER PRIMARY KEY,event TEXT NOT NULL,"
                    "user_id TEXT,session_id TEXT,occurred_at TEXT NOT NULL,ip TEXT NOT NULL DEFAULT '')"
                )
            with patch.object(admin_store, "ADMIN_DB", database_path):
                admin_store.init()
                admin_store.record_event("legacy_schema_check", actor_role="admin", actor_id="operator")
                event = admin_store.activity_log()[0]
        self.assertEqual(event["actor_role"], "admin")
        self.assertEqual(event["actor_id"], "operator")


if __name__ == "__main__":
    unittest.main()
