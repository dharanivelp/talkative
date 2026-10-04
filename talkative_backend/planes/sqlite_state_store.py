import fcntl
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from threading import local

from talkative_backend.config import STATE_DB


class SQLiteStateStore:
    def __init__(self):
        self.path = Path(STATE_DB)
        self._local = local()

    def init(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS state_values (
                    key TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    expires_at REAL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS state_sorted_members (
                    key TEXT NOT NULL,
                    member TEXT NOT NULL,
                    score REAL NOT NULL,
                    PRIMARY KEY (key, member)
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS state_sorted_score ON state_sorted_members(key, score, member)")
            db.execute("PRAGMA journal_mode=WAL")

    def ping(self):
        with self._connect() as db:
            db.execute("SELECT 1").fetchone()
        return True

    @contextmanager
    def _connect(self):
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            yield connection
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        os.chmod(self.path, 0o600)
        db.execute("PRAGMA busy_timeout=5000")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _begin_write(db):
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")

    def _purge_expired(self, db, key):
        db.execute("DELETE FROM state_values WHERE key=? AND expires_at IS NOT NULL AND expires_at<=?", (key, time.time()))

    @contextmanager
    def lock(self, name, timeout=None, blocking_timeout=None):
        lock_name = hashlib.sha256(name.encode("utf-8")).hexdigest()
        lock_path = self.path.with_name(f"{self.path.name}.{lock_name}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock_file:
            os.chmod(lock_path, 0o600)
            wait = blocking_timeout if blocking_timeout is not None else timeout
            deadline = time.monotonic() + wait if wait is not None else None
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if deadline is not None and time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out acquiring state lock: {name}")
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def get(self, key):
        with self._connect() as db:
            self._purge_expired(db, key)
            row = db.execute("SELECT kind, value FROM state_values WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        if row[0] != "string":
            raise TypeError(f"State key {key!r} does not contain a string")
        return row[1]

    def set(self, key, value, nx=False, ex=None):
        with self._connect() as db:
            self._begin_write(db)
            self._purge_expired(db, key)
            exists = db.execute("SELECT 1 FROM state_values WHERE key=?", (key,)).fetchone()
            if nx and exists:
                return None
            expires_at = time.time() + float(ex) if ex is not None else None
            db.execute(
                "INSERT INTO state_values(key, kind, value, expires_at) VALUES(?, 'string', ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET kind='string', value=excluded.value, expires_at=excluded.expires_at",
                (key, str(value), expires_at),
            )
        return True

    def hset(self, key, mapping):
        with self._connect() as db:
            self._begin_write(db)
            self._purge_expired(db, key)
            row = db.execute("SELECT kind, value FROM state_values WHERE key=?", (key,)).fetchone()
            if row and row[0] != "hash":
                raise TypeError(f"State key {key!r} does not contain a hash")
            values = json.loads(row[1]) if row else {}
            added = sum(1 for field in mapping if field not in values)
            values.update({str(field): str(value) for field, value in mapping.items()})
            db.execute(
                "INSERT INTO state_values(key, kind, value, expires_at) VALUES(?, 'hash', ?, NULL) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(values)),
            )
        return added

    def hget(self, key, field):
        values = self.hgetall(key)
        return values.get(field)

    def hgetall(self, key):
        with self._connect() as db:
            self._purge_expired(db, key)
            row = db.execute("SELECT kind, value FROM state_values WHERE key=?", (key,)).fetchone()
        if not row:
            return {}
        if row[0] != "hash":
            raise TypeError(f"State key {key!r} does not contain a hash")
        return json.loads(row[1])

    def hdel(self, key, *fields):
        with self._connect() as db:
            self._begin_write(db)
            self._purge_expired(db, key)
            row = db.execute("SELECT kind, value FROM state_values WHERE key=?", (key,)).fetchone()
            if not row:
                return 0
            if row[0] != "hash":
                raise TypeError(f"State key {key!r} does not contain a hash")
            values = json.loads(row[1])
            removed = sum(1 for field in fields if field in values)
            for field in fields:
                values.pop(field, None)
            if values:
                db.execute("UPDATE state_values SET value=? WHERE key=?", (json.dumps(values), key))
            else:
                db.execute("DELETE FROM state_values WHERE key=?", (key,))
        return removed

    def delete(self, *keys):
        removed = 0
        with self._connect() as db:
            self._begin_write(db)
            for key in keys:
                exists = db.execute(
                    "SELECT 1 FROM state_values WHERE key=? UNION SELECT 1 FROM state_sorted_members WHERE key=? LIMIT 1",
                    (key, key),
                ).fetchone()
                if exists:
                    removed += 1
                db.execute("DELETE FROM state_values WHERE key=?", (key,))
                db.execute("DELETE FROM state_sorted_members WHERE key=?", (key,))
        return removed

    def incr(self, key):
        with self._connect() as db:
            self._begin_write(db)
            self._purge_expired(db, key)
            row = db.execute("SELECT kind, value, expires_at FROM state_values WHERE key=?", (key,)).fetchone()
            if row and row[0] != "string":
                raise TypeError(f"State key {key!r} does not contain a string")
            try:
                count = int(row[1]) + 1 if row else 1
            except ValueError as error:
                raise ValueError(f"State key {key!r} is not an integer") from error
            expires_at = row[2] if row else None
            db.execute(
                "INSERT INTO state_values(key, kind, value, expires_at) VALUES(?, 'string', ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(count), expires_at),
            )
        return count

    def expire(self, key, seconds):
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE state_values SET expires_at=? WHERE key=?",
                (time.time() + float(seconds), key),
            )
            return cursor.rowcount == 1

    def zadd(self, key, mapping):
        with self._connect() as db:
            self._begin_write(db)
            row = db.execute("SELECT kind FROM state_values WHERE key=?", (key,)).fetchone()
            if row and row[0] != "zset":
                raise TypeError(f"State key {key!r} does not contain a sorted set")
            db.execute(
                "INSERT INTO state_values(key, kind, value, expires_at) VALUES(?, 'zset', '', NULL) "
                "ON CONFLICT(key) DO NOTHING",
                (key,),
            )
            added = 0
            for member, score in mapping.items():
                exists = db.execute(
                    "SELECT 1 FROM state_sorted_members WHERE key=? AND member=?",
                    (key, str(member)),
                ).fetchone()
                cursor = db.execute(
                    "INSERT INTO state_sorted_members(key, member, score) VALUES(?, ?, ?) "
                    "ON CONFLICT(key, member) DO UPDATE SET score=excluded.score",
                    (key, str(member), float(score)),
                )
                added += int(exists is None and cursor.rowcount > 0)
        return added

    @staticmethod
    def _score_bound(value):
        if value in ("-inf", "-Infinity"):
            return float("-inf"), True
        if value in ("+inf", "inf", "Infinity"):
            return float("inf"), True
        text = str(value)
        if text.startswith("("):
            return float(text[1:]), False
        return float(text), True

    def zremrangebyscore(self, key, minimum, maximum):
        low, low_inclusive = self._score_bound(minimum)
        high, high_inclusive = self._score_bound(maximum)
        lower = ">=" if low_inclusive else ">"
        upper = "<=" if high_inclusive else "<"
        with self._connect() as db:
            removed = db.execute(
                f"DELETE FROM state_sorted_members WHERE key=? AND score {lower} ? AND score {upper} ?",
                (key, low, high),
            ).rowcount
            remaining = db.execute("SELECT 1 FROM state_sorted_members WHERE key=? LIMIT 1", (key,)).fetchone()
            if not remaining:
                db.execute("DELETE FROM state_values WHERE key=? AND kind='zset'", (key,))
        return removed

    def zcard(self, key):
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM state_sorted_members WHERE key=?", (key,)).fetchone()[0]

    def zrem(self, key, *members):
        with self._connect() as db:
            removed = sum(
                db.execute("DELETE FROM state_sorted_members WHERE key=? AND member=?", (key, str(member))).rowcount
                for member in members
            )
            remaining = db.execute("SELECT 1 FROM state_sorted_members WHERE key=? LIMIT 1", (key,)).fetchone()
            if not remaining:
                db.execute("DELETE FROM state_values WHERE key=? AND kind='zset'", (key,))
        return removed

    def zscore(self, key, member):
        with self._connect() as db:
            row = db.execute(
                "SELECT score FROM state_sorted_members WHERE key=? AND member=?", (key, str(member))
            ).fetchone()
        return row[0] if row else None

    def zrange(self, key, start, stop):
        with self._connect() as db:
            members = [
                row[0]
                for row in db.execute(
                    "SELECT member FROM state_sorted_members WHERE key=? ORDER BY score, member", (key,)
                )
            ]
        start = int(start)
        stop = int(stop)
        if start < 0:
            start = max(0, len(members) + start)
        if stop < 0:
            stop = len(members) + stop
        return members[start : stop + 1]

    def zrangebyscore(self, key, minimum, maximum):
        low, low_inclusive = self._score_bound(minimum)
        high, high_inclusive = self._score_bound(maximum)
        lower = ">=" if low_inclusive else ">"
        upper = "<=" if high_inclusive else "<"
        with self._connect() as db:
            return [
                row[0]
                for row in db.execute(
                    f"SELECT member FROM state_sorted_members WHERE key=? AND score {lower} ? AND score {upper} ? "
                    "ORDER BY score, member",
                    (key, low, high),
                )
            ]

    def exists(self, key):
        with self._connect() as db:
            self._purge_expired(db, key)
            value_exists = db.execute("SELECT 1 FROM state_values WHERE key=?", (key,)).fetchone()
            if value_exists:
                return 1
            return int(db.execute("SELECT 1 FROM state_sorted_members WHERE key=? LIMIT 1", (key,)).fetchone() is not None)

    def verify_challenge(self, key, digest, max_attempts, verified_key=None, ttl_seconds=None):
        with self._connect() as db:
            self._begin_write(db)
            self._purge_expired(db, key)
            row = db.execute("SELECT kind, value, expires_at FROM state_values WHERE key=?", (key,)).fetchone()
            if not row:
                return [0, ""]
            if row[0] != "hash":
                raise TypeError(f"State key {key!r} does not contain a hash")
            state = json.loads(row[1])
            if state.get("otp_hash") != digest:
                attempts = int(state.get("attempts", "0")) + 1
                if attempts >= int(max_attempts):
                    db.execute("DELETE FROM state_values WHERE key=?", (key,))
                else:
                    state["attempts"] = str(attempts)
                    db.execute("UPDATE state_values SET value=? WHERE key=?", (json.dumps(state), key))
                return [-1, ""]
            payload = state.get("payload", "")
            if verified_key:
                expires_at = time.time() + float(ttl_seconds)
                db.execute(
                    "INSERT INTO state_values(key, kind, value, expires_at) VALUES(?, 'string', ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET kind='string', value=excluded.value, expires_at=excluded.expires_at",
                    (verified_key, payload, expires_at),
                )
            db.execute("DELETE FROM state_values WHERE key=?", (key,))
            return [1, payload]

    def pipeline(self, transaction=True):
        return SQLitePipeline(self, transaction)


class SQLitePipeline:
    def __init__(self, client, transaction=True):
        self.client = client
        self.transaction = transaction
        self.commands = []

    def __getattr__(self, name):
        method = getattr(self.client, name)
        if not callable(method):
            raise AttributeError(name)

        def enqueue(*args, **kwargs):
            self.commands.append((method, args, kwargs))
            return self

        return enqueue

    def execute(self):
        commands, self.commands = self.commands, []

        def run_commands():
            return [method(*args, **kwargs) for method, args, kwargs in commands]

        if not self.transaction:
            return run_commands()

        with self.client._connect() as db:
            self.client._begin_write(db)
            self.client._local.connection = db
            try:
                return run_commands()
            finally:
                del self.client._local.connection


client = SQLiteStateStore()
