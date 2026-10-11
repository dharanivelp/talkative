import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, session
import pycountry

from talkative_backend.core.functions import age_category, audit, current_user, is_eligible, message_flags, parse_dob, public_profile_details, timestamp
from talkative_backend.config import GLOBAL_CHAT_SIMULATION_ENABLED
from talkative_backend.planes import admin_store, user_store
from talkative_backend.planes import sqlite_chat_store as chat_store

chat_bp = Blueprint("chat", __name__)
GLOBAL_CHAT_SIMULATION_EPOCH = 1_767_225_600
GLOBAL_CHAT_SIMULATION_INTERVAL = 6
GLOBAL_CHAT_SIMULATION_HISTORY = 50
GLOBAL_CHAT_SIMULATION_MESSAGES = (
    ("Aarav Sharma", "Anyone following the cricket matches this week? The last few overs have been so tense."),
    ("Ananya Iyer", "I watched a new film this weekend. Any recommendations for what to watch next?"),
    ("Karthik R.", "Tried one of those AI tools to plan a trip. It made a surprisingly useful itinerary."),
    ("Nila S.", "The weather is finally good for an evening walk. What are your favorite spots?"),
    ("Vignesh Kumar", "The cricket highlights are all over my feed today. Which team are you cheering for?"),
    ("Meena Lakshmi", "I found a lovely little filter coffee place nearby. Always happy to discover local cafes."),
    ("Arjun P.", "Has anyone tried using AI to learn a new language? Curious how helpful it is."),
    ("Kavya Subramanian", "Looking for a new playlist for my commute. Share your favorites!"),
    ("Rohan Mehta", "What small thing made you smile today?"),
    ("Zoya Khan", "I started a book with a really unexpected opening. What are you reading lately?"),
    ("Dev Patel", "Finally tried cooking a dish I usually order out. It turned out better than expected!"),
    ("Isha Nair", "If you could take a weekend trip anywhere nearby, where would you go?"),
    ("Maya Das", "I need a new podcast for long walks. Any recommendations?"),
    ("Kabir Rao", "Spent the afternoon exploring a part of town I had never visited before."),
    ("Priya Menon", "What's your go-to comfort meal after a busy day?"),
    ("Neil Joseph", "I made a playlist for a friend and now I keep listening to it myself."),
    ("Sana Ali", "Anyone else enjoy rainy afternoons with a cup of tea and no plans?"),
    ("Aditya Bose", "Trying to get better at taking photos. What's your favorite subject to shoot?"),
    ("Tara Sen", "Just learned a few phrases in a new language. It's fun being a beginner again."),
    ("Manav Shah", "What's a hobby you'd like to make more time for this year?"),
    ("Leela Krishnan", "I found a quiet park with the nicest walking trail this morning."),
    ("Omar Farooq", "What song have you had on repeat lately?"),
    ("Riya Kapoor", "A friend introduced me to a board game I had never heard of. Any favorites?"),
    ("Sam Thomas", "I finally fixed something at home that I had been putting off for weeks."),
    ("Aditi Roy", "Do you prefer planning a trip in detail or figuring it out as you go?"),
    ("Farah Sheikh", "Trying a new recipe tonight. Fingers crossed it works out!"),
    ("Ibrahim Khan", "What's the best live show or concert you've been to?"),
    ("Neha Pillai", "I started stretching in the morning and it makes waking up a little easier."),
    ("Jay Shah", "What place would you happily visit again and again?"),
    ("Pooja Nair", "I love hearing how people spend a slow weekend. What does yours look like?"),
    ("Ravi Verma", "Found a great little second-hand bookshop today. I could browse for hours."),
    ("Mina Paul", "What's something useful you learned from a friend recently?"),
    ("Sahil Gupta", "A long walk with good music is still my favorite way to reset."),
    ("Divya Rao", "Would you rather watch a documentary or a comedy tonight?"),
    ("Aman Gill", "I tried drawing again after ages. It was relaxing, even if I'm rusty."),
    ("Nandini Sen", "What are your favorite ways to explore a new city?"),
    ("Ethan D'Souza", "A stranger recommended a song to me today and it was exactly my kind of music."),
    ("Saira Ahmed", "What's one thing you're looking forward to this week?"),
    ("Varun Nair", "I took the scenic route home and found a new cafe along the way."),
    ("Mira Joshi", "Do you have a favorite game to play with friends?"),
    ("Arun Das", "I set aside an hour to do nothing today. More people should try it."),
)


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


@chat_bp.get("/api/global-chat/simulation")
def global_chat_simulation_messages():
    if not GLOBAL_CHAT_SIMULATION_ENABLED:
        return jsonify(error="Global chat simulation is disabled."), 404

    after = request.args.get("after")
    if after is not None:
        try:
            after = max(0, int(after))
        except ValueError:
            return jsonify(error="invalid message cursor"), 400

    current_slot = max(0, int((time.time() - GLOBAL_CHAT_SIMULATION_EPOCH) // GLOBAL_CHAT_SIMULATION_INTERVAL))
    cursor = max(current_slot, after or 0)
    first_slot = max(
        1,
        ((current_slot - 1) // GLOBAL_CHAT_SIMULATION_HISTORY) * GLOBAL_CHAT_SIMULATION_HISTORY + 1,
    )
    reset = after is not None and after < first_slot
    if after is not None and not reset:
        first_slot = max(first_slot, after + 1)

    messages = []
    for slot in range(first_slot, current_slot + 1):
        name, text = GLOBAL_CHAT_SIMULATION_MESSAGES[(slot * 7 + slot // len(GLOBAL_CHAT_SIMULATION_MESSAGES)) % len(GLOBAL_CHAT_SIMULATION_MESSAGES)]
        messages.append({
            "id": slot,
            "name": name,
            "text": text,
            "created_at": datetime.fromtimestamp(
                GLOBAL_CHAT_SIMULATION_EPOCH + slot * GLOBAL_CHAT_SIMULATION_INTERVAL,
                timezone.utc,
            ).isoformat(),
            "mine": False,
            "simulated": True,
        })

    return jsonify(messages=messages, cursor=cursor, reset=reset)


@chat_bp.get("/api/global-chat")
def global_chat_messages():
    user = current_user()
    after = request.args.get("after")
    if after is not None:
        try:
            after = max(0, int(after))
        except ValueError:
            return jsonify(error="invalid message cursor"), 400

    preview_remaining = None
    if not user:
        started_at = session.get("global_chat_preview_started_at")
        if not isinstance(started_at, (int, float)):
            started_at = time.time()
            session["global_chat_preview_started_at"] = started_at
        preview_remaining = max(0, int(started_at + 120 - time.time() + 0.999))
        if preview_remaining == 0:
            return jsonify(
                messages=[],
                authenticated=False,
                preview_expired=True,
                preview_remaining=0,
            )

    messages = chat_store.global_chat_messages(after)
    for message in messages:
        sender_user_id = message.pop("sender_user_id", None)
        message["mine"] = bool(user and sender_user_id == user["user_id"])

    return jsonify(
        messages=messages,
        authenticated=bool(user),
        preview_expired=False,
        preview_remaining=preview_remaining,
    )


@chat_bp.post("/api/global-chat")
def send_global_chat_message():
    user = current_user()
    if not user:
        return jsonify(error="Please log in to send a global chat message."), 401
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    if not isinstance(text, str):
        return jsonify(error="message must be 1-128 characters"), 400
    text = text.strip()
    if not text or len(text) > 128:
        return jsonify(error="message must be 1-128 characters"), 400
    flags = message_flags(text)
    if flags:
        audit("global_chat_message_blocked", user["user_id"])
        return jsonify(blocked=True, flags=flags), 400
    message_id = chat_store.add_global_chat_message(
        user["user_id"], user["first_name"], text, timestamp()
    )
    if message_id is None:
        return jsonify(error="Please wait a moment before sending another message."), 429
    audit("global_chat_message_sent", user["user_id"])
    return jsonify(ok=True, id=message_id)


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


@chat_bp.post("/api/stay-in-touch/<string:session_id>")
def stay_in_touch(session_id):
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    action = (request.get_json(silent=True) or {}).get("action", "accept")
    if action == "accept":
        consent = chat_store.agree_stay_in_touch(session_id, user["user_id"])
    elif action == "decline":
        consent = chat_store.decline_stay_in_touch(session_id, user["user_id"])
    else:
        return jsonify(error="invalid stay-in-touch response"), 400
    if not consent:
        return jsonify(error="no active request to stay in touch"), 404

    result = consent["result"]
    if result != "declined" and consent["by_me"] and consent["by_peer"]:
        result, _ = user_store.add_contact_pair(
            consent["user_a"], consent["user_b"], timestamp()
        )
        chat_store.set_stay_in_touch_result(session_id, result)
        if result == "connected":
            audit("contacts_mutually_added", user["user_id"], session_id)

    return jsonify(
        agreed_by_me=consent["by_me"],
        agreed_by_peer=consent["by_peer"],
        result=result,
    )


@chat_bp.get("/api/contacts")
def contacts():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    items = user_store.list_contacts(user["user_id"])
    for contact in items:
        peer_id = contact.pop("peer_user_id")
        peer = user_store.by_user_id(peer_id)
        contact["peer"] = _peer_view(peer) if peer else None
        if contact["peer"]:
            contact["peer"]["online"] = chat_store.is_online(peer_id)
            contact["peer"]["last_seen"] = chat_store.last_seen(peer_id)
    return jsonify(contacts=items, limit=user_store.CONTACT_LIMIT)


@chat_bp.delete("/api/contacts/<string:conversation_id>")
def remove_contact(conversation_id):
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    if not user_store.remove_contact(user["user_id"], conversation_id):
        return jsonify(error="contact not found"), 404
    audit("contact_removed")
    return jsonify(ok=True)


@chat_bp.get("/api/contact-messages/<string:conversation_id>")
def get_contact_messages(conversation_id):
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    raw_after = request.args.get("after")
    try:
        after = max(0, int(raw_after)) if raw_after is not None else None
    except ValueError:
        return jsonify(error="invalid message cursor"), 400
    messages = user_store.contact_message_history(user["user_id"], conversation_id, after)
    if messages is None:
        return jsonify(error="contact not found"), 404
    peer_id = user_store.contact_peer(user["user_id"], conversation_id)
    return jsonify(
        messages=messages,
        typing=chat_store.contact_peer_typing(conversation_id, peer_id),
        peer_presence={
            "online": chat_store.is_online(peer_id),
            "last_seen": chat_store.last_seen(peer_id),
        },
    )


@chat_bp.post("/api/contact-typing/<string:conversation_id>")
def contact_typing(conversation_id):
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    if user_store.contact_peer(user["user_id"], conversation_id) is None:
        return jsonify(error="contact not found"), 404
    chat_store.set_contact_typing(conversation_id, user["user_id"])
    return jsonify(ok=True)


@chat_bp.post("/api/contact-messages/<string:conversation_id>")
def send_contact_message(conversation_id):
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    text = str((request.get_json(silent=True) or {}).get("text", "")).strip()
    if not text or len(text) > 128:
        return jsonify(error="message must be 1-128 characters"), 400
    if user_store.contact_peer(user["user_id"], conversation_id) is None:
        return jsonify(error="contact not found"), 404
    flags = message_flags(text)
    if flags:
        audit("contact_message_blocked", user["user_id"])
        return jsonify(blocked=True, flags=flags), 400
    if not user_store.add_contact_message(
        user["user_id"], conversation_id, text, timestamp()
    ):
        return jsonify(error="contact not found"), 404
    audit("contact_message_sent", user["user_id"])
    return jsonify(ok=True)


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
