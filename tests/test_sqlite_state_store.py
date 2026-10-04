import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from talkative_backend.planes import sqlite_state_store


class SQLiteStateStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database_path = Path(self.directory.name) / "state.db"
        self.path_patcher = patch.object(sqlite_state_store, "STATE_DB", self.database_path)
        self.path_patcher.start()
        self.addCleanup(self.path_patcher.stop)
        self.store = sqlite_state_store.SQLiteStateStore()
        self.store.init()

    def test_state_survives_reopening_and_expires(self):
        self.store.set("temporary", "value", ex=0.03)
        self.store.hset("challenge", mapping={"payload": "{}"})
        reopened = sqlite_state_store.SQLiteStateStore()
        self.assertEqual(reopened.get("temporary"), "value")
        self.assertEqual(reopened.hget("challenge", "payload"), "{}")

        time.sleep(0.04)
        self.assertIsNone(reopened.get("temporary"))

    def test_sorted_set_uses_score_and_exclusive_bounds(self):
        self.assertEqual(self.store.zadd("queue", {"later": 3, "first": 1, "middle": 2}), 3)
        self.assertEqual(self.store.zadd("queue", {"middle": 4}), 0)
        self.assertEqual(self.store.zrange("queue", 0, -1), ["first", "later", "middle"])
        self.assertEqual(self.store.zscore("queue", "middle"), 4)
        self.assertEqual(self.store.zrangebyscore("queue", "(1", "+inf"), ["later", "middle"])
        self.assertEqual(self.store.zremrangebyscore("queue", "-inf", 2), 1)
        self.assertEqual(self.store.zcard("queue"), 2)

    def test_challenge_attempts_are_limited_and_success_consumes_state(self):
        self.store.hset("challenge", mapping={
            "otp_hash": "expected",
            "payload": '{"user_id":"u1"}',
            "attempts": "0",
        })
        self.store.expire("challenge", 60)
        self.assertEqual(self.store.verify_challenge("challenge", "wrong", 2), [-1, ""])
        self.assertEqual(self.store.verify_challenge("challenge", "wrong", 2), [-1, ""])
        self.assertEqual(self.store.hgetall("challenge"), {})

        self.store.hset("challenge", mapping={
            "otp_hash": "expected",
            "payload": '{"user_id":"u1"}',
            "attempts": "0",
        })
        result = self.store.verify_challenge(
            "challenge", "expected", 5, verified_key="verified", ttl_seconds=30
        )
        self.assertEqual(result, [1, '{"user_id":"u1"}'])
        self.assertEqual(self.store.get("verified"), '{"user_id":"u1"}')
        self.assertEqual(self.store.hgetall("challenge"), {})

    def test_pipeline_and_lock_support_atomic_match_operations(self):
        with self.store.lock("match", timeout=1, blocking_timeout=1):
            pipe = self.store.pipeline(transaction=True)
            pipe.set("session:a", "dm1")
            pipe.set("session:b", "dm1")
            pipe.execute()
        self.assertEqual(self.store.get("session:a"), "dm1")
        self.assertEqual(self.store.get("session:b"), "dm1")

    def test_pipeline_rolls_back_all_commands_when_one_fails(self):
        pipe = self.store.pipeline(transaction=True)
        pipe.set("first", "persist only if committed")
        pipe.hset("first", mapping={"field": "wrong type"})
        with self.assertRaises(TypeError):
            pipe.execute()
        self.assertIsNone(self.store.get("first"))


if __name__ == "__main__":
    unittest.main()
