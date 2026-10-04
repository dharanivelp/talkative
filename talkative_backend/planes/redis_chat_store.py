import json
import time
import uuid
from datetime import datetime, timezone

import redis

from talkative_backend.config import REDIS_PASSWORD, REDIS_URL

client = redis.Redis.from_url(REDIS_URL, password=REDIS_PASSWORD or None, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)
PREFIX = "talkative:"
PRESENCE_TIMEOUT = 25


def init():
    client.ping()


def _session_key(session_id):
    return f"{PREFIX}session:{session_id}"


def _messages_key(session_id):
    return f"{PREFIX}messages:{session_id}"


def touch_presence(user_id):
    now = time.time()
    key = f"{PREFIX}online"
    client.zadd(key, {user_id: now})
    client.zremrangebyscore(key, "-inf", now - PRESENCE_TIMEOUT)
    return client.zcard(key)


def online_count():
    key = f"{PREFIX}online"
    client.zremrangebyscore(key, "-inf", time.time() - PRESENCE_TIMEOUT)
    return client.zcard(key)


def remove_presence(user_id):
    client.zrem(f"{PREFIX}online", user_id)


def is_online(user_id):
    score = client.zscore(f"{PREFIX}online", user_id)
    return score is not None and time.time() - score <= PRESENCE_TIMEOUT


def match_or_queue(user_id, is_blocked, timestamp, ip_address=""):
    queue_key = f"{PREFIX}queue"
    with client.lock(f"{PREFIX}match-lock", timeout=5, blocking_timeout=5):
        existing = client.get(f"{PREFIX}user-session:{user_id}")
        if existing:
            state = client.hgetall(_session_key(existing))
            if state and not state.get("ended_at"):
                return "matched", existing, None
        now = time.time()
        client.zremrangebyscore(queue_key, "-inf", now - 180)
        for peer_id in client.zrange(queue_key, 0, -1):
            if peer_id == user_id or is_blocked(user_id, peer_id):
                continue
            session_id = "dm" + uuid.uuid4().hex
            peer_ip = client.get(f"{PREFIX}user-ip:{peer_id}") or ""
            pipe = client.pipeline(transaction=True)
            pipe.zrem(queue_key, user_id, peer_id)
            pipe.hset(_session_key(session_id), mapping={
                "session_id": session_id,
                "user_a": peer_id,
                "user_b": user_id,
                "started_at": timestamp,
                "ended_at": "",
                "duration_seconds": "0",
                "ip_a": peer_ip,
                "ip_b": ip_address or "",
            })
            pipe.set(f"{PREFIX}user-session:{peer_id}", session_id)
            pipe.set(f"{PREFIX}user-session:{user_id}", session_id)
            pipe.delete(f"{PREFIX}user-ip:{peer_id}", f"{PREFIX}user-ip:{user_id}")
            pipe.execute()
            return "matched", session_id, peer_id
        client.zadd(queue_key, {user_id: now})
        if ip_address:
            client.set(f"{PREFIX}user-ip:{user_id}", ip_address, ex=180)
        return "waiting", None, None


def user_session(session_id, user_id):
    state = client.hgetall(_session_key(session_id))
    if not state or user_id not in (state.get("user_a"), state.get("user_b")):
        return None
    state["duration_seconds"] = int(state.get("duration_seconds", 0))
    return state


def read_messages(session_id, user_id, after):
    state = user_session(session_id, user_id)
    if not state:
        return None
    peer_id = state["user_b"] if state["user_a"] == user_id else state["user_a"]
    messages = []
    for encoded in client.zrangebyscore(_messages_key(session_id), f"({after}", "+inf"):
        message = json.loads(encoded)
        messages.append({"id": message["id"], "text": message["text"], "mine": message["sender_user_id"] == user_id})
    typing_key = f"{PREFIX}typing:{session_id}:{peer_id}"
    leave_until = float(state.get("leave_until") or 0)
    leave_pending = bool(state.get("leave_by")) and leave_until > time.time()
    return {
        "messages": messages,
        "typing": client.exists(typing_key) == 1 and not leave_pending,
        "ended": bool(state.get("ended_at")),
        "leave_pending": leave_pending,
        "leave_by_me": leave_pending and state.get("leave_by") == user_id,
        "leave_seconds": max(0, int(leave_until - time.time() + 0.999)) if leave_pending else 0,
        "leave_until": leave_until if leave_pending else 0,
        "peer_online": is_online(peer_id),
    }


def begin_leave(session_id, user_id, seconds=5):
    key = _session_key(session_id)
    with client.lock(f"{PREFIX}leave-lock:{session_id}", timeout=5, blocking_timeout=5):
        state = user_session(session_id, user_id)
        if not state or state.get("ended_at"):
            return None
        existing_until = float(state.get("leave_until") or 0)
        if state.get("leave_by") and existing_until > time.time():
            return {"leave_by_me": state["leave_by"] == user_id, "leave_until": existing_until}
        leave_until = time.time() + seconds
        client.hset(key, mapping={"leave_by": user_id, "leave_until": leave_until})
        return {"leave_by_me": True, "leave_until": leave_until}


def cancel_leave(session_id, user_id):
    key = _session_key(session_id)
    with client.lock(f"{PREFIX}leave-lock:{session_id}", timeout=5, blocking_timeout=5):
        state = user_session(session_id, user_id)
        if not state or state.get("ended_at") or state.get("leave_by") != user_id:
            return False
        if float(state.get("leave_until") or 0) <= time.time():
            return False
        client.hdel(key, "leave_by", "leave_until")
        return True


def set_typing(session_id, user_id, timestamp):
    state = user_session(session_id, user_id)
    if not state or state.get("ended_at") or (state.get("leave_by") and float(state.get("leave_until") or 0) > time.time()):
        return False
    peer_key = f"{PREFIX}typing:{session_id}:{user_id}"
    client.set(peer_key, timestamp, ex=2)
    return True


def add_message(session_id, user_id, text, timestamp):
    state = user_session(session_id, user_id)
    if not state or state.get("ended_at") or (state.get("leave_by") and float(state.get("leave_until") or 0) > time.time()):
        return False
    sequence_key = f"{PREFIX}sequence:{session_id}"
    sequence = client.incr(sequence_key)
    payload = json.dumps({"id": sequence, "sender_user_id": user_id, "text": text, "created_at": timestamp})
    client.zadd(_messages_key(session_id), {payload: sequence})
    return True


def end_session(session_id, user_id, timestamp):
    key = _session_key(session_id)
    with client.lock(f"{PREFIX}end-lock:{session_id}", timeout=5, blocking_timeout=5):
        state = user_session(session_id, user_id)
        if not state or state.get("ended_at"):
            return None
        started = datetime.fromisoformat(state["started_at"])
        ended = datetime.fromisoformat(timestamp)
        seconds = max(0, int((ended - started).total_seconds()))
        transcript = [json.loads(item) for item in client.zrange(_messages_key(session_id), 0, -1)]
        client.hset(key, mapping={"ended_at": timestamp, "duration_seconds": seconds})
        client.hdel(key, "leave_by", "leave_until")
        client.expire(key, 86400)
        return {**state, "ended_at": timestamp, "duration_seconds": seconds, "transcript": transcript}


def cleanup_ended(session_id):
    state = client.hgetall(_session_key(session_id))
    if not state or not state.get("ended_at"):
        return
    with client.lock(f"{PREFIX}match-lock", timeout=5, blocking_timeout=5):
        state = client.hgetall(_session_key(session_id))
        if not state or not state.get("ended_at"):
            return
        user_session_keys = [
            f"{PREFIX}user-session:{state.get('user_a')}",
            f"{PREFIX}user-session:{state.get('user_b')}",
        ]
        keys_to_delete = [
            _messages_key(session_id),
            f"{PREFIX}sequence:{session_id}",
            f"{PREFIX}typing:{session_id}:{state.get('user_a')}",
            f"{PREFIX}typing:{session_id}:{state.get('user_b')}",
        ]
        keys_to_delete.extend(
            key for key in user_session_keys if client.get(key) == session_id
        )
        if keys_to_delete:
            client.delete(*keys_to_delete)


def leave_queue(user_id):
    client.zrem(f"{PREFIX}queue", user_id)
