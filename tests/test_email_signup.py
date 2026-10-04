import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from talkative_backend.backend import auth
from talkative_backend.planes import user_store


class MemoryStateStore:
    def __init__(self):
        self.values = {}
        self.hashes = {}

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def expire(self, key, seconds):
        return True

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def hset(self, key, mapping):
        self.hashes[key] = dict(mapping)

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def delete(self, *keys):
        for key in keys:
            self.hashes.pop(key, None)
            self.values.pop(key, None)

    def verify_challenge(self, key, digest, max_attempts, verified_key=None, ttl_seconds=None):
        state = self.hashes.get(key)
        if not state:
            return [0, ""]
        if state["otp_hash"] != digest:
            state["attempts"] = str(int(state["attempts"]) + 1)
            if int(state["attempts"]) >= max_attempts:
                self.hashes.pop(key, None)
            return [-1, ""]
        payload = state["payload"]
        if verified_key:
            self.values[verified_key] = payload
        self.hashes.pop(key, None)
        return [1, payload]


class SignupEmailOtpTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test-session-secret"
        self.app.register_blueprint(auth.auth_bp)
        self.client = self.app.test_client()
        self.state_store = MemoryStateStore()
        self.environment_patcher = patch.object(auth, "APP_ENV", "development")
        self.environment_patcher.start()
        self.addCleanup(self.environment_patcher.stop)
        self.state_patcher = patch.object(auth.chat_store, "client", self.state_store)
        self.state_patcher.start()
        self.addCleanup(self.state_patcher.stop)

    def signup_data(self):
        return {
            "terms_accepted": True,
            "email": "person@example.com",
            "password": "LongEnoughPass123!",
            "first_name": "Test",
            "last_name": "Person",
            "gender": "prefer_not_to_say",
            "country_code": "IN",
            "date_of_birth": "1990-01-01",
        }

    @patch.object(auth.user_store, "by_email", return_value=None)
    @patch.object(auth, "is_eligible", return_value=True)
    @patch.object(auth.user_store, "create_user")
    @patch.object(auth.user_store, "by_username", return_value=None)
    def test_signup_waits_for_fixed_email_otp_and_username_before_creating_user(self, by_username, create_user, *_):
        create_user.return_value = "usr_test"
        response = self.client.post("/api/auth/signup", json=self.signup_data())
        self.assertEqual(response.status_code, 200)
        create_user.assert_not_called()

        with patch.object(auth, "audit"):
            response = self.client.post(
                "/api/auth/verify-signup-email",
                json={"email": "person@example.com", "code": "123456"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("signup_token", response.json)
        create_user.assert_not_called()

        with patch.object(auth, "audit"):
            response = self.client.post(
                "/api/auth/complete-signup",
                json={"signup_token": response.json["signup_token"], "username": "person123"},
            )
        self.assertEqual(response.status_code, 200)
        create_user.assert_called_once()

    def test_signup_fails_closed_in_production(self):
        with patch.object(auth, "APP_ENV", "production"):
            response = self.client.post("/api/auth/signup", json=self.signup_data())
        self.assertEqual(response.status_code, 503)

    @patch.object(auth, "audit")
    @patch.object(auth, "check_password_hash", return_value=True)
    @patch.object(auth.user_store, "by_email")
    def test_login_requires_otp_before_creating_session(self, by_email, check_password, audit):
        by_email.return_value = {
            "user_id": "usr_login",
            "password_hash": "hash",
            "password_reset_required": 0,
            "admin_blocked": 0,
        }
        response = self.client.post(
            "/api/auth/login", json={"email": "person@example.com", "password": "correct"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["otp_required"])
        self.assertEqual(response.json["message"], "Enter the verification code to continue.")
        with self.client.session_transaction() as user_session:
            self.assertNotIn("user_id", user_session)

        response = self.client.post(
            "/api/auth/verify-login-otp",
            json={"challenge_id": response.json["challenge_id"], "code": "123456"},
        )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as user_session:
            self.assertEqual(user_session["user_id"], "usr_login")
        self.assertTrue(any(call.args[0] == "login_succeeded" for call in audit.call_args_list))

    @patch.object(auth, "check_password_hash", return_value=True)
    @patch.object(auth.user_store, "by_email")
    def test_login_fails_closed_in_production(self, by_email, check_password):
        by_email.return_value = {
            "user_id": "usr_login",
            "password_hash": "hash",
            "password_reset_required": 0,
            "admin_blocked": 0,
        }
        with patch.object(auth, "APP_ENV", "production"):
            response = self.client.post(
                "/api/auth/login", json={"email": "person@example.com", "password": "correct"}
            )
        self.assertEqual(response.status_code, 503)

    def test_signup_rejects_removed_phone_field(self):
        data = self.signup_data()
        data["phone_number"] = "+911234567890"
        response = self.client.post("/api/auth/signup", json=data)
        self.assertEqual(response.status_code, 400)

    def test_user_database_migration_removes_saved_phone_column(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "users.db"
            legacy_path = Path(directory) / "missing-legacy.db"
            with patch.object(user_store, "USER_DB", database_path), patch.object(user_store, "LEGACY_DB", legacy_path):
                user_store.init()
                with sqlite3.connect(database_path) as db:
                    db.execute("ALTER TABLE users ADD COLUMN phone_number TEXT NOT NULL DEFAULT ''")
                    db.execute(
                        "INSERT INTO users(user_id,email,password_hash,name,date_of_birth,gender,created_at,phone_number) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        ("usr_old", "old@example.com", "hash", "Old User", "1990-01-01", "male", "2020-01-01", "+911234567890"),
                    )
                user_store.init()
                with sqlite3.connect(database_path) as db:
                    columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
                    row = db.execute("SELECT user_id FROM users WHERE user_id='usr_old'").fetchone()
                self.assertNotIn("phone_number", columns)
                self.assertEqual(row[0], "usr_old")

    def test_user_database_migration_renames_degree_fields_and_preserves_values(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "users.db"
            legacy_path = Path(directory) / "missing-legacy.db"
            with patch.object(user_store, "USER_DB", database_path), patch.object(user_store, "LEGACY_DB", legacy_path):
                user_store.init()
                with sqlite3.connect(database_path) as db:
                    db.execute("ALTER TABLE users RENAME COLUMN education TO degree")
                    db.execute("ALTER TABLE users RENAME COLUMN show_education TO show_degree")
                    db.execute(
                        "INSERT INTO users(user_id,email,password_hash,name,date_of_birth,gender,created_at,degree,show_degree) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        ("usr_education", "education@example.com", "hash", "Education User", "1990-01-01", "male", "2020-01-01", "Bachelor's", 1),
                    )
                user_store.init()
                with sqlite3.connect(database_path) as db:
                    columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
                    row = db.execute(
                        "SELECT education,show_education FROM users WHERE user_id='usr_education'"
                    ).fetchone()
                self.assertIn("education", columns)
                self.assertIn("show_education", columns)
                self.assertNotIn("degree", columns)
                self.assertNotIn("show_degree", columns)
                self.assertEqual(row, ("Bachelor's", 1))

    @patch.object(auth, "audit")
    @patch.object(auth.user_store, "update_profile")
    @patch.object(auth.user_store, "by_username", return_value=None)
    @patch.object(auth, "current_user")
    def test_profile_api_uses_education_field(self, current_user, by_username, update_profile, audit):
        current_user.return_value = {
            "user_id": "usr_education",
            "username": "person123",
            "bio": "",
            "profession": "",
            "education": "",
            "location": "",
            "show_bio": 0,
            "show_profession": 0,
            "show_education": 0,
            "show_location": 0,
            "country_code": "IN",
        }
        response = self.client.post(
            "/api/profile", json={"education": "M.Tech.", "show_education": True}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(update_profile.call_args.args[4], "M.Tech.")
        self.assertTrue(update_profile.call_args.args[8])

        response = self.client.post("/api/profile", json={"degree": "Bachelor's"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["error"], "Unsupported profile field")
        for field in ("bio", "profession"):
            response = self.client.post("/api/profile", json={field: "x" * 33})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json["error"], f"{field.title()} must be 32 characters or fewer")

    def test_email_is_unique_case_insensitively(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(user_store, "USER_DB", Path(directory) / "users.db"), patch.object(
                user_store, "LEGACY_DB", Path(directory) / "missing-legacy.db"
            ):
                user_store.init()
                args = ("person@example.com", "person123", "hash", "Test", "Person", "1990-01-01", "male", "IN", "2026-01-01", "terms", "2026-01-01")
                user_store.create_user(*args)
                with self.assertRaises(sqlite3.IntegrityError):
                    user_store.create_user("PERSON@example.com", *args[1:])

    @patch.object(auth.user_store, "create_user", return_value="usr_admin")
    @patch.object(auth, "audit")
    def test_admin_provisioned_account_is_created_only_after_email_otp(self, audit, create_user):
        email = "new.user@example.com"
        code = "123456"
        payload = {
            "email": email,
            "username": "newuser",
            "password_hash": "temporary-hash",
            "first_name": "New",
            "last_name": "User",
            "dob": "1990-01-01",
            "gender": "prefer_not_to_say",
            "country_code": "IN",
            "terms_accepted_at": "2026-01-01",
            "password_reset_required": True,
            "admin_created": True,
        }
        key = f"{auth.chat_store.PREFIX}signup-otp:{auth._email_key(email)}"
        self.state_store.hashes[key] = {
            "otp_hash": auth._otp_digest(email, code),
            "payload": json.dumps(payload),
            "attempts": "0",
        }

        response = self.client.post(
            "/api/auth/verify-signup-email", json={"email": email, "code": code}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["password_reset_required"])
        create_user.assert_called_once()
        with self.client.session_transaction() as user_session:
            self.assertEqual(user_session["role"], "password_reset")
