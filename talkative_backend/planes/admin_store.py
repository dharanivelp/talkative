import os
import json
import hashlib
import hmac
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from talkative_backend.config import ACTIVITY_LOG_RETENTION_DAYS, ADMIN_DB, SESSION_SECRET

RETENTION = timedelta(days=1)
ANALYTICS_RETENTION = timedelta(days=400)
INCIDENT_EVENTS = {"message_blocked", "user_blocked", "chat_connection_lost"}
ACTIVE_EVENTS = {"account_created", "login_succeeded", "chat_started", "message_sent", "user_reported", "user_blocked"}


def connect():
    ADMIN_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ADMIN_DB, timeout=10)
    db.row_factory = sqlite3.Row
    os.chmod(ADMIN_DB, 0o600)
    return db


@contextmanager
def database():
    db = connect()
    try:
        with db:
            yield db
    finally:
        db.close()


def activity_retention_days(db):
    row = db.execute("SELECT value FROM settings WHERE key='activity_log_retention_days'").fetchone()
    try:
        return max(1, min(180, int(float(row["value"])))) if row else ACTIVITY_LOG_RETENTION_DAYS
    except ValueError:
        return ACTIVITY_LOG_RETENTION_DAYS


def purge(db):
    now = datetime.now(timezone.utc)
    transcript_cutoff = (now - RETENTION).isoformat()
    analytics_cutoff = (now - ANALYTICS_RETENTION).date().isoformat()
    db.execute("UPDATE chat_history SET transcript_json='[]' WHERE ended_at IS NOT NULL AND ended_at<? AND transcript_json!='[]'", (transcript_cutoff,))
    db.execute("DELETE FROM chat_history WHERE ended_at IS NOT NULL AND ended_at<?", (transcript_cutoff,))
    log_cutoff = (now - timedelta(days=activity_retention_days(db))).isoformat()
    db.execute("DELETE FROM accounting WHERE occurred_at<?", (log_cutoff,))
    db.execute("DELETE FROM app_logs WHERE occurred_at<?", (log_cutoff,))
    db.execute("DELETE FROM daily_metrics WHERE day<?", (analytics_cutoff,))
    db.execute("DELETE FROM daily_active_users WHERE day<?", (analytics_cutoff,))


def init():
    with database() as db:
        db.executescript("""CREATE TABLE IF NOT EXISTS chat_history(
            session_id TEXT PRIMARY KEY,
            user_a_id TEXT NOT NULL,
            user_b_id TEXT NOT NULL,
            ip_a TEXT NOT NULL DEFAULT '',
            ip_b TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL,
            ended_at TEXT,
            duration_seconds INTEGER,
            transcript_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS accounting(
            id INTEGER PRIMARY KEY,
            event TEXT NOT NULL,
            user_id TEXT,
            session_id TEXT,
            occurred_at TEXT NOT NULL,
            ip TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS accounting_time_idx ON accounting(occurred_at);
        CREATE INDEX IF NOT EXISTS accounting_user_idx ON accounting(user_id,occurred_at);
        CREATE TABLE IF NOT EXISTS app_logs(
            id INTEGER PRIMARY KEY,
            occurred_at TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            ip TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS app_logs_time_idx ON app_logs(occurred_at);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS daily_metrics(
            day TEXT PRIMARY KEY,
            new_users INTEGER NOT NULL DEFAULT 0,
            incidents INTEGER NOT NULL DEFAULT 0,
            reports INTEGER NOT NULL DEFAULT 0,
            chats INTEGER NOT NULL DEFAULT 0,
            chat_seconds INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS daily_active_users(
            day TEXT NOT NULL,
            user_hash TEXT NOT NULL,
            PRIMARY KEY(day,user_hash)
        );""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(chat_history)")}
        if "transcript_json" not in columns:
            db.execute("ALTER TABLE chat_history ADD COLUMN transcript_json TEXT NOT NULL DEFAULT '[]'")
        for column in ("ip_a", "ip_b"):
            if column not in columns:
                db.execute(f"ALTER TABLE chat_history ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        if "ip" not in {row[1] for row in db.execute("PRAGMA table_info(accounting)")}:
            db.execute("ALTER TABLE accounting ADD COLUMN ip TEXT NOT NULL DEFAULT ''")
        purge(db)


def record_session(session_id, user_a_id, user_b_id, started_at, ip_a="", ip_b=""):
    with database() as db:
        purge(db)
        db.execute("INSERT OR IGNORE INTO chat_history(session_id,user_a_id,user_b_id,ip_a,ip_b,started_at) VALUES(?,?,?,?,?,?)",
                   (session_id, user_a_id, user_b_id, ip_a or "", ip_b or "", started_at))


def finish_session(session_id, ended_at, duration_seconds, transcript):
    with database() as db:
        purge(db)
        row = db.execute("SELECT ended_at FROM chat_history WHERE session_id=?", (session_id,)).fetchone()
        if not row or row["ended_at"]:
            return
        db.execute("UPDATE chat_history SET ended_at=?,duration_seconds=?,transcript_json=? WHERE session_id=?",
                   (ended_at, duration_seconds, json.dumps(transcript, separators=(",", ":")), session_id))
        day = ended_at[:10]
        db.execute("INSERT OR IGNORE INTO daily_metrics(day) VALUES(?)", (day,))
        db.execute("UPDATE daily_metrics SET chats=chats+1,chat_seconds=chat_seconds+? WHERE day=?",
                   (max(0, int(duration_seconds or 0)), day))


def record_event(event, user_id=None, session_id=None, ip=""):
    with database() as db:
        purge(db)
        occurred_at = datetime.now(timezone.utc).isoformat()
        day = occurred_at[:10]
        db.execute("INSERT INTO accounting(event,user_id,session_id,occurred_at,ip) VALUES(?,?,?,?,?)", (event, user_id, session_id, occurred_at, ip or ""))
        if event == "account_created" or event in INCIDENT_EVENTS or event == "user_reported":
            db.execute("INSERT OR IGNORE INTO daily_metrics(day) VALUES(?)", (day,))
            column = "new_users" if event == "account_created" else "reports" if event == "user_reported" else "incidents"
            db.execute(f"UPDATE daily_metrics SET {column}={column}+1 WHERE day=?", (day,))
        if user_id and event in ACTIVE_EVENTS:
            user_hash = hmac.new(SESSION_SECRET.encode(), user_id.encode(), hashlib.sha256).hexdigest()
            db.execute("INSERT OR IGNORE INTO daily_active_users(day,user_hash) VALUES(?,?)", (day, user_hash))


def dashboard_metrics(start_day, end_day):
    with database() as db:
        purge(db)
        totals = db.execute("""SELECT COALESCE(SUM(new_users),0) AS new_users,
            COALESCE(SUM(incidents),0) AS incidents, COALESCE(SUM(reports),0) AS reports,
            COALESCE(SUM(chats),0) AS chats, COALESCE(SUM(chat_seconds),0) AS chat_seconds
            FROM daily_metrics WHERE day>=? AND day<=?""", (start_day, end_day)).fetchone()
        active = db.execute("SELECT COUNT(DISTINCT user_hash) FROM daily_active_users WHERE day>=? AND day<=?",
                             (start_day, end_day)).fetchone()[0]
        return {**dict(totals), "active_users": active}


def search_sessions(query="", user_ids=(), ip="", start="", end="", limit=200):
    where, params = [], []
    query = str(query or "").strip()
    if query:
        like = f"%{query}%"
        parts = ["session_id LIKE ?", "user_a_id LIKE ?", "user_b_id LIKE ?"]
        params += [like, like, like]
        if user_ids:
            marks = ",".join("?" * len(user_ids))
            parts += [f"user_a_id IN ({marks})", f"user_b_id IN ({marks})"]
            params += list(user_ids) * 2
        where.append("(" + " OR ".join(parts) + ")")
    ip = str(ip or "").strip()
    if ip:
        where.append("(ip_a LIKE ? OR ip_b LIKE ?)")
        params += [f"%{ip}%"] * 2
    if start:
        where.append("started_at>=?")
        params.append(start)
    if end:
        where.append("started_at<=?")
        params.append(end)
    clause = "WHERE " + " AND ".join(where) if where else ""
    with database() as db:
        purge(db)
        return [dict(row) for row in db.execute(
            f"SELECT session_id,user_a_id,user_b_id,ip_a,ip_b,started_at,ended_at,duration_seconds FROM chat_history {clause} ORDER BY started_at DESC LIMIT ?",
            (*params, max(1, min(500, int(limit)))),
        )]


def get_settings():
    with database() as db:
        return {row["key"]: row["value"] for row in db.execute("SELECT key,value FROM settings")}


def set_settings(values):
    with database() as db:
        db.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       [(key, str(value)) for key, value in values.items()])


def log_event(level, message, ip=""):
    with database() as db:
        db.execute("INSERT INTO app_logs(occurred_at,level,message,ip) VALUES(?,?,?,?)",
                   (datetime.now(timezone.utc).isoformat(), level, str(message)[:500], ip or ""))


def activity_log(query="", limit=200):
    query = str(query or "").strip()
    like = f"%{query}%"
    with database() as db:
        purge(db)
        return [dict(row) for row in db.execute(
            "SELECT occurred_at,event,user_id,session_id,ip FROM accounting WHERE (?='' OR event LIKE ? OR user_id LIKE ? OR session_id LIKE ? OR ip LIKE ?) ORDER BY id DESC LIMIT ?",
            (query, like, like, like, like, max(1, min(500, int(limit)))),
        )]


def production_logs(query="", level="", limit=200):
    query = str(query or "").strip()
    like = f"%{query}%"
    with database() as db:
        purge(db)
        return [dict(row) for row in db.execute(
            "SELECT occurred_at,level,message,ip FROM app_logs WHERE (?='' OR level=?) AND (?='' OR message LIKE ? OR ip LIKE ?) ORDER BY id DESC LIMIT ?",
            (level, level, query, like, like, max(1, min(500, int(limit)))),
        )]


def user_activity(user_id, limit=300):
    with database() as db:
        purge(db)
        return [dict(row) for row in db.execute(
            "SELECT occurred_at,event,session_id,ip FROM accounting WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, max(1, min(500, int(limit)))),
        )]


def session_details(session_id):
    with database() as db:
        purge(db)
        row = db.execute("SELECT * FROM chat_history WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["transcript"] = json.loads(item.pop("transcript_json", "[]"))
        item["activities"] = [dict(event) for event in db.execute(
            "SELECT event,user_id,occurred_at FROM accounting WHERE session_id=? ORDER BY occurred_at",
            (session_id,),
        )]
        return item
