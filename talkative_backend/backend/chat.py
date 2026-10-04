import time

from flask import Blueprint, jsonify, request
import pycountry

from talkative_backend.core.functions import age_category, audit, current_user, is_eligible, message_flags, parse_dob, public_profile_details, timestamp
from talkative_backend.planes import admin_store, user_store
from talkative_backend.planes import sqlite_chat_store as chat_store

chat_bp = Blueprint("chat", __name__)


def _peer_view(peer):
    country = pycountry.countries.get(alpha_2=peer["country_code"])
    view = {
        "name": peer["first_name"],
        "age_category": age_category(parse_dob(peer["date_of_birth"])),
        "gender": peer["gender"],
        "score": peer["quality_score"],
        "streak_days": peer["current_streak_days"],
        "country_code": peer["country_code"],
        "country_name": country.name if country else "",
    }
    view.update(public_profile_details(peer))
    return view


@chat_bp.post("/api/match")
def match():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    if not is_eligible(parse_dob(user["date_of_birth"])):
        return jsonify(error="You are not eligible to chat"), 403
    mode, session_id, peer_id = chat_store.match_or_queue(
        user["user_id"], user_store.are_blocked, timestamp(), request.remote_addr or ""
    )
    user_store.set_active([user["user_id"]], True)
    if mode == "waiting":
        return jsonify(status="waiting")
    session_row = chat_store.user_session(session_id, user["user_id"])
    peer_id = peer_id or (session_row["user_b"] if session_row["user_a"] == user["user_id"] else session_row["user_a"])
    user_store.set_active([peer_id], True)
    peer = user_store.by_user_id(peer_id)
    peer_view = _peer_view(peer)
    admin_store.record_session(session_id, session_row["user_a"], session_row["user_b"], session_row["started_at"],
                               session_row.get("ip_a", ""), session_row.get("ip_b", ""))
    audit("chat_started", user["user_id"], session_id)
    return jsonify(status="matched", conversation_id=session_id,
                   peer=peer_view)


@chat_bp.get("/api/active-chat")
def active_chat():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    session_id = chat_store.client.get(f"{chat_store.PREFIX}user-session:{user['user_id']}")
    session_row = chat_store.user_session(session_id, user["user_id"]) if session_id else None
    if not session_row or session_row.get("ended_at"):
        return jsonify(active=False)
    peer_id = session_row["user_b"] if session_row["user_a"] == user["user_id"] else session_row["user_a"]
    peer = user_store.by_user_id(peer_id)
    if not peer:
        return jsonify(active=False)
    return jsonify(active=True, conversation_id=session_id, peer=_peer_view(peer))


@chat_bp.get("/api/messages/<string:session_id>")
def get_messages(session_id):
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    try:
        after = max(0, int(request.args.get("after", 0)))
    except ValueError:
        return jsonify(error="invalid message cursor"), 400
    state = chat_store.read_messages(session_id, user["user_id"], after)
    if state is None:
        return jsonify(error="not found"), 404
    if not state["ended"] and not state["peer_online"]:
        ended = chat_store.end_session(session_id, user["user_id"], timestamp())
        if ended:
            for participant in (ended["user_a"], ended["user_b"]):
                user_store.update_score(participant, seconds=ended["duration_seconds"])
            admin_store.finish_session(session_id, ended["ended_at"], ended["duration_seconds"], ended["transcript"])
            chat_store.cleanup_ended(session_id)
            audit("chat_connection_lost", user["user_id"], session_id)
        state["ended"] = True
        state["connection_lost"] = True
    return jsonify(state)


@chat_bp.post("/api/typing/<string:session_id>")
def typing(session_id):
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    if not chat_store.set_typing(session_id, user["user_id"], time.time()):
        return jsonify(error="not found"), 404
    return jsonify(ok=True)


@chat_bp.post("/api/leave/begin")
def begin_leave():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    session_id = str((request.get_json(silent=True) or {}).get("session_id", ""))
    leave = chat_store.begin_leave(session_id, user["user_id"], seconds=5)
    if not leave:
        return jsonify(error="no active chat"), 404
    audit("chat_leave_started", user["user_id"], session_id)
    return jsonify(ok=True, leave_by_me=leave["leave_by_me"], leave_until=leave["leave_until"])


@chat_bp.post("/api/leave/cancel")
def cancel_leave():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    session_id = str((request.get_json(silent=True) or {}).get("session_id", ""))
    if not chat_store.cancel_leave(session_id, user["user_id"]):
        return jsonify(error="leave countdown cannot be cancelled"), 409
    audit("chat_leave_cancelled", user["user_id"], session_id)
    return jsonify(ok=True)


@chat_bp.post("/api/messages/<string:session_id>")
def send_message(session_id):
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    text = str((request.get_json(silent=True) or {}).get("text", "")).strip()
    if not text or len(text) > 128:
        return jsonify(error="message must be 1-128 characters"), 400
    session_state = chat_store.user_session(session_id, user["user_id"])
    if not session_state:
        return jsonify(error="not found"), 404
    if session_state.get("leave_by") and float(session_state.get("leave_until") or 0) > time.time():
        return jsonify(error="messages are paused while the chat is ending"), 423
    flags = message_flags(text)
    if flags:
        user_store.update_score(user["user_id"], flagged=True)
        audit("message_blocked", user["user_id"], session_id)
        return jsonify(blocked=True, flags=flags)
    if not chat_store.add_message(session_id, user["user_id"], text, timestamp()):
        return jsonify(error="chat has ended"), 410
    user_store.update_score(user["user_id"], clean=True)
    audit("message_sent", user["user_id"], session_id)
    return jsonify(ok=True)


@chat_bp.post("/api/leave")
def leave():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    user_id = user["user_id"]
    chat_store.leave_queue(user_id)
    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id", ""))
    if not session_id:
        return jsonify(ok=True)
    if not data.get("cancel_match"):
        session_state = chat_store.user_session(session_id, user_id)
        if not session_state:
            return jsonify(error="not found"), 404
        leave_until = float(session_state.get("leave_until") or 0)
        if not session_state.get("leave_by"):
            leave = chat_store.begin_leave(session_id, user_id, seconds=5)
            if not leave:
                return jsonify(error="no active chat"), 404
            return jsonify(pending=True, leave_until=leave["leave_until"]), 202
        if leave_until > time.time():
            return jsonify(pending=True, leave_until=leave_until), 202
    ended = chat_store.end_session(session_id, user_id, timestamp())
    if not ended:
        return jsonify(ok=True)
    for participant in (ended["user_a"], ended["user_b"]):
        user_store.update_score(participant, seconds=ended["duration_seconds"])
    admin_store.finish_session(session_id, ended["ended_at"], ended["duration_seconds"], ended["transcript"])
    chat_store.cleanup_ended(session_id)
    audit("chat_ended", user_id, session_id)
    return jsonify(ok=True)


@chat_bp.post("/api/report")
def report():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    session_id = str((request.get_json(silent=True) or {}).get("session_id", ""))
    session_row = chat_store.user_session(session_id, user["user_id"])
    if not session_row or session_row["ended_at"] is not None:
        return jsonify(error="no active chat"), 400
    peer_id = session_row["user_b"] if session_row["user_a"] == user["user_id"] else session_row["user_a"]
    user_store.update_score(peer_id, reported=True)
    audit("user_reported", user["user_id"], session_id)
    return jsonify(ok=True)


@chat_bp.post("/api/block")
def block():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    session_id = str((request.get_json(silent=True) or {}).get("session_id", ""))
    session_row = chat_store.user_session(session_id, user["user_id"])
    if not session_row or session_row["ended_at"] is not None:
        return jsonify(error="no active chat"), 400
    peer_id = session_row["user_b"] if session_row["user_a"] == user["user_id"] else session_row["user_a"]
    user_store.block_pair(user["user_id"], peer_id, timestamp())
    audit("user_blocked", user["user_id"], session_id)
    ended = chat_store.end_session(session_id, user["user_id"], timestamp())
    if ended:
        for participant in (ended["user_a"], ended["user_b"]):
            user_store.update_score(participant, seconds=ended["duration_seconds"])
        admin_store.finish_session(session_id, ended["ended_at"], ended["duration_seconds"], ended["transcript"])
        chat_store.cleanup_ended(session_id)
    chat_store.leave_queue(user["user_id"])
    return jsonify(ok=True)


@chat_bp.get("/api/score")
def score():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    user = user_store.by_user_id(user["user_id"])
    return jsonify(score=user["quality_score"], chat_seconds=user["total_chat_seconds"],
                   reports_received=user["reports_received"], moderation_events=user["moderation_events"])
