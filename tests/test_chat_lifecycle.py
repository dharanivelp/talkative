import unittest
from contextlib import nullcontext
from unittest.mock import patch

from talkative_backend.planes import redis_chat_store


class MemoryRedis:
    def __init__(self, session_id, user_a, user_b, current_sessions):
        self.hashes = {
            f"{redis_chat_store.PREFIX}session:{session_id}": {
                "ended_at": "2026-10-04T00:00:00+00:00",
                "user_a": user_a,
                "user_b": user_b,
            }
        }
        self.values = dict(current_sessions)
        self.deleted = []

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def get(self, key):
        return self.values.get(key)

    def lock(self, *_args, **_kwargs):
        return nullcontext()

    def delete(self, *keys):
        self.deleted.extend(keys)
        for key in keys:
            self.values.pop(key, None)


class ChatLifecycleTests(unittest.TestCase):
    def test_cleanup_does_not_remove_a_newer_user_session(self):
        ended_session = "dm-ended"
        new_session = "dm-new"
        user_a_key = f"{redis_chat_store.PREFIX}user-session:user-a"
        user_b_key = f"{redis_chat_store.PREFIX}user-session:user-b"
        redis = MemoryRedis(
            ended_session,
            "user-a",
            "user-b",
            {user_a_key: new_session, user_b_key: ended_session},
        )

        with patch.object(redis_chat_store, "client", redis):
            redis_chat_store.cleanup_ended(ended_session)

        self.assertEqual(redis.values[user_a_key], new_session)
        self.assertNotIn(user_a_key, redis.deleted)
        self.assertNotIn(user_b_key, redis.values)
        self.assertIn(user_b_key, redis.deleted)


if __name__ == "__main__":
    unittest.main()
