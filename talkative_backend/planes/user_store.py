import hashlib
import os
import re
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from talkative_backend.config import LEGACY_DB, USER_DB


def connect():
    USER_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(USER_DB, timeout=10)
    db.row_factory = sqlite3.Row
    os.chmod(USER_DB, 0o600)
    return db


@contextmanager
def database():
    db = connect()
    try:
        with db:
            yield db
    finally:
        db.close()


def init():
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL COLLATE NOCASE UNIQUE,
            username TEXT,
            password_hash TEXT NOT NULL,
            password_reset_required INTEGER NOT NULL DEFAULT 0,
            admin_blocked INTEGER NOT NULL DEFAULT 0,
            admin_blocked_at TEXT,
            name TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            date_of_birth TEXT NOT NULL,
            gender TEXT NOT NULL,
            bio TEXT NOT NULL DEFAULT '',
            profession TEXT NOT NULL DEFAULT '',
            education TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            show_bio INTEGER NOT NULL DEFAULT 0,
            show_profession INTEGER NOT NULL DEFAULT 0,
            show_education INTEGER NOT NULL DEFAULT 0,
            show_location INTEGER NOT NULL DEFAULT 0,
            country_code TEXT NOT NULL DEFAULT 'ZZ',
            quality_score INTEGER NOT NULL DEFAULT 50,
            current_streak_days INTEGER NOT NULL DEFAULT 0,
            last_active_date TEXT,
            total_chat_seconds INTEGER NOT NULL DEFAULT 0,
            reports_received INTEGER NOT NULL DEFAULT 0,
            moderation_events INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            terms_version TEXT,
            terms_accepted_at TEXT
        )""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        if "degree" in columns and "education" not in columns:
            db.execute("ALTER TABLE users RENAME COLUMN degree TO education")
            columns.remove("degree")
            columns.add("education")
        elif "degree" in columns:
            db.execute("UPDATE users SET education=degree WHERE education='' AND degree IS NOT NULL")
            db.execute("ALTER TABLE users DROP COLUMN degree")
            columns.remove("degree")
        if "show_degree" in columns and "show_education" not in columns:
            db.execute("ALTER TABLE users RENAME COLUMN show_degree TO show_education")
            columns.remove("show_degree")
            columns.add("show_education")
        elif "show_degree" in columns:
            db.execute("UPDATE users SET show_education=show_degree WHERE show_education=0")
            db.execute("ALTER TABLE users DROP COLUMN show_degree")
            columns.remove("show_degree")
        if "username" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN username TEXT")
        if "password_reset_required" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN password_reset_required INTEGER NOT NULL DEFAULT 0")
        if "admin_blocked" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN admin_blocked INTEGER NOT NULL DEFAULT 0")
        if "admin_blocked_at" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN admin_blocked_at TEXT")
        if "country_code" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN country_code TEXT NOT NULL DEFAULT 'ZZ'")
        if "phone_number" in columns:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("UPDATE users SET phone_number=''")
            db.execute("ALTER TABLE users DROP COLUMN phone_number")
        if "terms_version" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN terms_version TEXT")
        if "terms_accepted_at" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN terms_accepted_at TEXT")
        if "current_streak_days" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN current_streak_days INTEGER NOT NULL DEFAULT 0")
        if "last_active_date" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN last_active_date TEXT")
        if "first_name" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
        if "last_name" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN last_name TEXT")
        for column in ("bio", "profession", "education", "location"):
            if column not in columns:
                db.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        for column in ("show_bio", "show_profession", "show_education", "show_location"):
            if column not in columns:
                db.execute(f"ALTER TABLE users ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
        db.execute("UPDATE users SET education='No formal education' WHERE education='No formal degree'")
        for row in db.execute("SELECT id FROM users WHERE username IS NULL OR username='' ").fetchall():
            db.execute("UPDATE users SET username=? WHERE id=?", (f"user{row['id']}", row["id"]))
        for row in db.execute("SELECT id,name FROM users WHERE first_name IS NULL OR last_name IS NULL").fetchall():
            parts = (row["name"] or "").strip().split(maxsplit=1)
            db.execute("UPDATE users SET first_name=?,last_name=? WHERE id=?", (parts[0] if parts else "", parts[1] if len(parts) > 1 else "", row["id"]))
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_username_unique ON users(username COLLATE NOCASE)")
        db.execute("CREATE TABLE IF NOT EXISTS blocks(user_id TEXT NOT NULL,blocked_user_id TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(user_id,blocked_user_id))")
        db.execute("CREATE TABLE IF NOT EXISTS legacy_user_map(legacy_id INTEGER PRIMARY KEY,user_id TEXT NOT NULL UNIQUE)")
        db.execute("CREATE TABLE IF NOT EXISTS deleted_user_emails(email_hash TEXT PRIMARY KEY)")
    migrate_legacy_users()


def migrate_legacy_users():
    if not LEGACY_DB.exists() or LEGACY_DB.resolve() == USER_DB.resolve():
        return
    legacy = sqlite3.connect(LEGACY_DB, timeout=10)
    legacy.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in legacy.execute("PRAGMA table_info(users)")}
        if not columns or "email" not in columns:
            return
        old_users = legacy.execute("SELECT * FROM users").fetchall()
    finally:
        legacy.close()
    with database() as db:
        for old in old_users:
            email = (old["email"] or "").strip().lower()
            if not email:
                continue
            email_hash = hashlib.sha256(email.encode("utf-8")).hexdigest()
            if db.execute("SELECT 1 FROM deleted_user_emails WHERE email_hash=?", (email_hash,)).fetchone():
                continue
            if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                continue
            birth_year = old["birth_year"] if "birth_year" in columns else None
            dob = f"{birth_year:04d}-01-01" if birth_year else "1900-01-01"
            password_hash = old["password_hash"] if "password_hash" in columns else None
            if not password_hash:
                password_hash = generate_password_hash(uuid.uuid4().hex)
            base_username = re.sub(r"[^a-z0-9_.-]", "_", email.split("@", 1)[0].lower()).strip("._-")[:20] or "member"
            username = base_username
            suffix = 1
            while db.execute("SELECT 1 FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone():
                ending = str(suffix)
                username = f"{base_username[:24-len(ending)]}{ending}"
                suffix += 1
            full_name = (old["display_name"] if "display_name" in columns else email.split("@", 1)[0]) or "User"
            name_parts = full_name.strip().split(maxsplit=1)
            first_name = name_parts[0] if name_parts else "User"
            last_name = name_parts[1] if len(name_parts) > 1 else ""
            db.execute("""INSERT OR IGNORE INTO users(
                user_id,email,username,password_hash,name,first_name,last_name,date_of_birth,gender,country_code,quality_score,
                total_chat_seconds,reports_received,moderation_events,active,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                "usr_" + uuid.uuid4().hex, email, username, password_hash,
                full_name, first_name, last_name,
                dob, old["gender"] if "gender" in columns and old["gender"] else "prefer_not_to_say", "ZZ",
                old["quality_score"] if "quality_score" in columns else 50,
                old["total_chat_seconds"] if "total_chat_seconds" in columns else 0,
                old["reports_received"] if "reports_received" in columns else 0,
                old["moderation_events"] if "moderation_events" in columns else 0,
                0, old["created_at"] if "created_at" in columns and old["created_at"] else date.today().isoformat()
            ))
            migrated = db.execute("SELECT user_id FROM users WHERE email=?", (email,)).fetchone()
            if "id" in columns:
                db.execute("INSERT OR IGNORE INTO legacy_user_map(legacy_id,user_id) VALUES(?,?)", (old["id"], migrated["user_id"]))
        try:
            old_blocks = legacy_blocks(LEGACY_DB)
        except sqlite3.Error:
            old_blocks = []
        for blocker, blocked, created in old_blocks:
            first = db.execute("SELECT user_id FROM legacy_user_map WHERE legacy_id=?", (blocker,)).fetchone()
            second = db.execute("SELECT user_id FROM legacy_user_map WHERE legacy_id=?", (blocked,)).fetchone()
            if first and second:
                db.execute("INSERT OR IGNORE INTO blocks(user_id,blocked_user_id,created_at) VALUES(?,?,?)", (first[0], second[0], created or date.today().isoformat()))


def legacy_blocks(path):
    with closing(sqlite3.connect(path)) as old_db:
        try:
            return old_db.execute("SELECT blocker_id,blocked_id,created_at FROM blocks").fetchall()
        except sqlite3.Error:
            return []


def by_email(email):
    with database() as db:
        return db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()


def by_username(username):
    with database() as db:
        return db.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()


def by_user_id(user_id):
    with database() as db:
        return db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


ADMIN_USER_FIELDS = "user_id,email,username,name,first_name,last_name,date_of_birth,gender,bio,profession,education,location,country_code,quality_score,current_streak_days,last_active_date,total_chat_seconds,reports_received,moderation_events,active,created_at,password_reset_required,admin_blocked,admin_blocked_at"


def admin_user_count():
    with database() as db:
        return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def admin_users(search="", limit=100, offset=0):
    search = str(search or "").strip()[:120]
    pattern = f"%{search}%"
    with database() as db:
        return [dict(row) for row in db.execute(
            f"SELECT {ADMIN_USER_FIELDS} FROM users WHERE (?='' OR user_id LIKE ? OR name LIKE ? OR username LIKE ? OR email LIKE ?) ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (search, pattern, pattern, pattern, pattern, max(1, min(100, int(limit))), max(0, int(offset))),
        )]


def admin_user_by_id(user_id):
    with database() as db:
        row = db.execute(f"SELECT {ADMIN_USER_FIELDS} FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def create_user(email, username, password_hash, first_name, last_name, dob, gender, country_code, created_at, terms_version, terms_accepted_at, password_reset_required=False):
    with database() as db:
        user_id = "usr_" + uuid.uuid4().hex
        while db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
            user_id = "usr_" + uuid.uuid4().hex
        name = f"{first_name} {last_name}".strip()
        db.execute("INSERT INTO users(user_id,email,username,password_hash,password_reset_required,name,first_name,last_name,date_of_birth,gender,country_code,created_at,terms_version,terms_accepted_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (user_id, email, username, password_hash, int(password_reset_required), name, first_name, last_name, dob, gender, country_code, created_at, terms_version, terms_accepted_at))
    return user_id


def update_profile(user_id, username, bio, profession, education, location, show_bio, show_profession, show_education, show_location):
    with database() as db:
        return db.execute("""UPDATE users SET username=?,bio=?,profession=?,education=?,location=?,
            show_bio=?,show_profession=?,show_education=?,show_location=? WHERE user_id=?""",
            (username, bio, profession, education, location, int(show_bio), int(show_profession), int(show_education), int(show_location), user_id)).rowcount


def update_password(user_id, password_hash):
    with database() as db:
        return db.execute("UPDATE users SET password_hash=?,password_reset_required=0 WHERE user_id=?", (password_hash, user_id)).rowcount


def set_admin_temporary_password(user_id, password_hash):
    with database() as db:
        return db.execute("UPDATE users SET password_hash=?,password_reset_required=1 WHERE user_id=?", (password_hash, user_id)).rowcount


def set_admin_blocked(user_id, blocked, blocked_at):
    with database() as db:
        return db.execute("UPDATE users SET admin_blocked=?,admin_blocked_at=?,active=0 WHERE user_id=?",
                          (int(blocked), blocked_at if blocked else None, user_id)).rowcount


def update_score(user_id, clean=False, flagged=False, reported=False, seconds=0):
    with database() as db:
        db.execute("""UPDATE users SET
            quality_score=CASE WHEN ? THEN MIN(100,quality_score+1) WHEN ? THEN MAX(0,quality_score-3) WHEN ? THEN MAX(0,quality_score-8) ELSE quality_score END,
            moderation_events=moderation_events+?,reports_received=reports_received+?,
            total_chat_seconds=total_chat_seconds+?,active=0
            WHERE user_id=?""", (clean, flagged, reported, int(flagged), int(reported), seconds, user_id))


def record_active_day(user_id, active_day):
    active_date = date.fromisoformat(active_day)
    with database() as db:
        user = db.execute("SELECT current_streak_days,last_active_date FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user:
            return 0
        if user["last_active_date"] == active_day:
            return user["current_streak_days"]
        previous_day = (active_date - timedelta(days=1)).isoformat()
        streak_days = user["current_streak_days"] + 1 if user["last_active_date"] == previous_day else 1
        db.execute("UPDATE users SET current_streak_days=?,last_active_date=? WHERE user_id=?", (streak_days, active_day, user_id))
        return streak_days


def set_active(user_ids, active):
    with database() as db:
        db.executemany("UPDATE users SET active=? WHERE user_id=?", [(int(active), item) for item in user_ids])


def are_blocked(first_id, second_id):
    with database() as db:
        return db.execute("SELECT 1 FROM blocks WHERE (user_id=? AND blocked_user_id=?) OR (user_id=? AND blocked_user_id=?)",
                          (first_id, second_id, second_id, first_id)).fetchone() is not None


def block_pair(user_id, blocked_user_id, created_at):
    with database() as db:
        db.execute("INSERT OR IGNORE INTO blocks(user_id,blocked_user_id,created_at) VALUES(?,?,?)", (user_id, blocked_user_id, created_at))


def delete_user(user_id):
    with database() as db:
        user = db.execute("SELECT email FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user:
            return 0
        email_hash = hashlib.sha256(user["email"].strip().lower().encode("utf-8")).hexdigest()
        db.execute("INSERT OR IGNORE INTO deleted_user_emails(email_hash) VALUES(?)", (email_hash,))
        db.execute("DELETE FROM blocks WHERE user_id=? OR blocked_user_id=?", (user_id, user_id))
        db.execute("DELETE FROM legacy_user_map WHERE user_id=?", (user_id,))
        return db.execute("DELETE FROM users WHERE user_id=?", (user_id,)).rowcount
