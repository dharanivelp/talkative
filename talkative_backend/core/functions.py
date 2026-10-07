from datetime import date, datetime, timezone

from flask import has_request_context, request, session

from talkative_backend.planes import admin_store, user_store

GENDERS = {"male", "female", "non_binary", "prefer_not_to_say"}
PASSWORD_REQUIREMENTS = "Use 12-256 characters with a lowercase letter, uppercase letter, number, and symbol. Do not use spaces or control characters."


def is_strong_password(password):
    return (
        isinstance(password, str)
        and 12 <= len(password) <= 256
        and any("a" <= char <= "z" for char in password)
        and any("A" <= char <= "Z" for char in password)
        and any("0" <= char <= "9" for char in password)
        and any(not char.isalnum() and not char.isspace() for char in password)
        and all(char.isprintable() and not char.isspace() for char in password)
    )


def parse_dob(value):
    value = str(value).strip()
    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.strptime(value, "%d/%m/%Y").date()


def is_eligible(dob):
    today = date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return years >= 18


def age_category(dob):
    today = date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if years < 25:
        return "18-24"
    if years < 35:
        return "25-34"
    if years < 45:
        return "35-44"
    if years < 55:
        return "45-54"
    return "55+"


def public_profile_details(user):
    return {
        field: user[field]
        for field in ("bio", "profession", "education", "location")
        if user[f"show_{field}"] and user[field].strip()
    }


def current_user():
    if session.get("role") != "user":
        return None
    user_id = session.get("user_id")
    user = user_store.by_user_id(user_id) if user_id else None
    return None if user and (user["password_reset_required"] or user["admin_blocked"]) else user


def user_authorized():
    return current_user() is not None


def admin_authorized():
    return session.get("role") == "admin" and bool(session.get("admin_username"))


def audit(event, user_id=None, session_id=None):
    actor_role = "anonymous"
    actor_id = ""
    if has_request_context():
        actor_role = session.get("role", "anonymous")
        actor_id = session.get("admin_username", "") if actor_role == "admin" else session.get("user_id", "")
    admin_store.record_event(
        event,
        user_id,
        session_id,
        request.remote_addr if has_request_context() else "",
        actor_role,
        actor_id,
    )


def message_flags(text):
    normalized = " ".join(text.lower().split())
    flags = []
    if any(word in normalized for word in ("idiot", "stupid", "moron", "loser")):
        flags.append("abuse")
    if any(term in normalized for term in ("send nudes", "nude", "explicit")):
        flags.append("sexual")
    if "http://" in normalized or "https://" in normalized:
        flags.append("link")
    return flags


def timestamp():
    return datetime.now(timezone.utc).isoformat()
