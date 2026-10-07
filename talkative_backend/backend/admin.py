import hmac
import math
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

import pycountry
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from talkative_backend.backend.auth import _send_signup_otp, close_user_activity
from talkative_backend.config import ADMIN_PASSWORD, ADMIN_TRANSCRIPT_KEY, ADMIN_USERNAME, ACTIVITY_LOG_RETENTION_DAYS, COMPANY_COST_CURRENCY, COMPANY_COST_PER_DAY
from talkative_backend.core.functions import admin_authorized, audit, is_eligible, parse_dob, timestamp
from talkative_backend.email_inbox import (
    InboxConfigurationError,
    InboxUnavailableError,
    MessageTooLargeError,
    list_messages,
    read_message,
)
from talkative_backend.planes import admin_store, user_store
from talkative_backend.planes import sqlite_chat_store as chat_store

admin_bp = Blueprint("admin", __name__)


def csrf_token():
    token = session.get("admin_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["admin_csrf_token"] = token
    return token


def csrf_valid():
    expected = str(session.get("admin_csrf_token", ""))
    supplied = str(request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", ""))
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def denied():
    return None if admin_authorized() else (jsonify(error="admin authentication required"), 401)


def period_range(period):
    today = datetime.now(timezone.utc).date()
    if period == "week":
        start = today - timedelta(days=today.weekday())
    elif period == "month":
        start = today.replace(day=1)
    elif period == "year":
        start = today.replace(month=1, day=1)
    else:
        period, start = "day", today
    return period, start.isoformat(), today.isoformat()


def filter_timestamp(value, end_of_day=False):
    value = str(value or "").strip()
    if not value:
        return ""
    if len(value) == 10:
        value += "T23:59:59.999999" if end_of_day else "T00:00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


@admin_bp.get("/admin")
def page():
    return render_template("admin.html", authorized=admin_authorized(), configured=bool(ADMIN_PASSWORD),
                           transcript_configured=bool(ADMIN_TRANSCRIPT_KEY), csrf_token=csrf_token(), error="")


@admin_bp.post("/admin/login")
def login():
    if not csrf_valid():
        return "Refresh and try again", 400
    username = str(request.form.get("username", ""))
    password = str(request.form.get("password", ""))
    valid = hmac.compare_digest(username, ADMIN_USERNAME) and bool(ADMIN_PASSWORD) and hmac.compare_digest(password, ADMIN_PASSWORD)
    if not valid:
        audit("admin_login_failed")
        return render_template("admin.html", authorized=False, configured=bool(ADMIN_PASSWORD), transcript_configured=bool(ADMIN_TRANSCRIPT_KEY), csrf_token=csrf_token(), error="Invalid credentials"), 401
    session.clear()
    session.update(role="admin", admin_username=username, admin_csrf_token=secrets.token_urlsafe(32))
    audit("admin_login_succeeded")
    return redirect(url_for("admin.page"))


@admin_bp.post("/admin/logout")
def logout():
    if not admin_authorized() or not csrf_valid():
        return "Forbidden", 403
    audit("admin_logout")
    session.clear()
    return redirect(url_for("admin.page"))


@admin_bp.get("/admin/api/dashboard")
def dashboard():
    if denied():
        return denied()
    period, start, end = period_range(request.args.get("period", "day"))
    values = admin_store.get_settings()
    try:
        cost = float(values.get("company_cost_per_day", COMPANY_COST_PER_DAY))
        if not math.isfinite(cost) or cost < 0:
            cost = 0.0
    except (TypeError, ValueError):
        cost = 0.0
    currency = str(values.get("company_cost_currency", COMPANY_COST_CURRENCY)).upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        currency = COMPANY_COST_CURRENCY
    metrics = admin_store.dashboard_metrics(start, end)
    metrics.update(period=period, start_day=start, end_day=end, total_users=user_store.admin_user_count(),
                   online_now=chat_store.online_count(), cost=cost, cost_rate=cost,
                   cost_currency=currency, cost_configured=cost > 0)
    return jsonify(metrics)


@admin_bp.get("/admin/api/users")
def users():
    if denied():
        return denied()
    try:
        limit = max(1, min(100, int(request.args.get("limit", 50))))
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        return jsonify(error="invalid pagination"), 400
    return jsonify(users=user_store.admin_users(request.args.get("q", ""), limit, offset),
                   total=user_store.admin_user_count(), offset=offset, limit=limit)


@admin_bp.get("/admin/api/users/<string:user_id>")
def user_details(user_id):
    if denied():
        return denied()
    user = user_store.admin_user_by_id(user_id)
    if not user:
        return jsonify(error="user not found"), 404
    return jsonify(user=user, activity=admin_store.user_activity(user_id))


@admin_bp.post("/admin/api/users")
def create_user():
    if denied():
        return denied()
    if not csrf_valid():
        return jsonify(error="invalid CSRF token"), 400
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    username = str(data.get("username", "")).strip()
    first = str(data.get("first_name", "")).strip()
    last = str(data.get("last_name", "")).strip()
    country_code = str(data.get("country_code", "")).strip().upper()
    gender = str(data.get("gender", "prefer_not_to_say"))
    try:
        dob = parse_dob(data.get("date_of_birth", ""))
    except (TypeError, ValueError):
        return jsonify(error="invalid birth date"), 400
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 254:
        return jsonify(error="invalid email"), 400
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,23}", username):
        return jsonify(error="invalid username"), 400
    if not first or not last or len(first) > 60 or len(last) > 60:
        return jsonify(error="enter first and last names up to 60 characters"), 400
    if gender not in {"male", "female", "non_binary", "prefer_not_to_say"} or not pycountry.countries.get(alpha_2=country_code):
        return jsonify(error="invalid country or gender"), 400
    if not is_eligible(dob):
        return jsonify(error="user must be 18 or older"), 400
    if user_store.by_email(email) or user_store.by_username(username):
        return jsonify(error="email or username already exists"), 409
    temporary = secrets.token_urlsafe(18)
    payload = {
        "email": email,
        "username": username,
        "password_hash": generate_password_hash(temporary),
        "first_name": first,
        "last_name": last,
        "dob": dob.isoformat(),
        "gender": gender,
        "country_code": country_code,
        "terms_accepted_at": timestamp(),
        "password_reset_required": True,
        "admin_created": True,
    }
    try:
        result, status = _send_signup_otp(email, payload)
    except sqlite3.Error:
        return jsonify(error="unable to start email verification"), 503
    if status != 200:
        return result, status
    response = jsonify(ok=True, verification_required=True, temporary_password=temporary)
    response.headers["Cache-Control"] = "no-store"
    return response, 202


@admin_bp.post("/admin/api/users/<string:user_id>/reset-password")
def reset_password(user_id):
    if denied():
        return denied()
    if not csrf_valid():
        return jsonify(error="invalid CSRF token"), 400
    if not user_store.admin_user_by_id(user_id):
        return jsonify(error="user not found"), 404
    temporary = secrets.token_urlsafe(18)
    user_store.set_admin_temporary_password(user_id, generate_password_hash(temporary))
    audit("admin_password_reset_issued", user_id)
    response = jsonify(ok=True, temporary_password=temporary, must_change_password=True)
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.post("/admin/api/users/<string:user_id>/block")
def block_user(user_id):
    if denied():
        return denied()
    if not csrf_valid():
        return jsonify(error="invalid CSRF token"), 400
    if not user_store.admin_user_by_id(user_id):
        return jsonify(error="user not found"), 404
    close_user_activity(user_id)
    user_store.set_admin_blocked(user_id, True, timestamp())
    audit("admin_user_blocked", user_id)
    return jsonify(ok=True)


@admin_bp.post("/admin/api/users/<string:user_id>/unblock")
def unblock_user(user_id):
    if denied():
        return denied()
    if not csrf_valid():
        return jsonify(error="invalid CSRF token"), 400
    if not user_store.set_admin_blocked(user_id, False, None):
        return jsonify(error="user not found"), 404
    audit("admin_user_unblocked", user_id)
    return jsonify(ok=True)


@admin_bp.delete("/admin/api/users/<string:user_id>")
def delete_user(user_id):
    if denied():
        return denied()
    if not csrf_valid():
        return jsonify(error="invalid CSRF token"), 400
    if not user_store.admin_user_by_id(user_id):
        return jsonify(error="user not found"), 404
    close_user_activity(user_id)
    user_store.delete_user(user_id)
    audit("admin_user_deleted", user_id)
    return jsonify(ok=True)


@admin_bp.get("/admin/api/sessions")
def sessions():
    if denied():
        return denied()
    try:
        start = filter_timestamp(request.args.get("start", ""))
        end = filter_timestamp(request.args.get("end", ""), end_of_day=True)
    except ValueError:
        return jsonify(error="invalid date or time filter"), 400
    user = request.args.get("user", "").strip()
    return jsonify(sessions=admin_store.search_sessions(request.args.get("q", ""), (user,) if user else (),
        request.args.get("ip", ""), start, end))


@admin_bp.post("/admin/api/transcripts/<string:session_id>")
def transcript(session_id):
    if denied():
        return denied()
    if not csrf_valid():
        return jsonify(error="invalid CSRF token"), 400
    if not ADMIN_TRANSCRIPT_KEY:
        return jsonify(error="Set ADMIN_TRANSCRIPT_KEY in .env"), 503
    supplied = str((request.get_json(silent=True) or {}).get("key", ""))
    if not hmac.compare_digest(supplied, ADMIN_TRANSCRIPT_KEY):
        audit("admin_transcript_key_denied", session_id=session_id)
        return jsonify(error="invalid transcript access key"), 403
    result = admin_store.session_details(session_id)
    if not result:
        return jsonify(error="chat not found or expired"), 404
    audit("admin_transcript_viewed", session_id=session_id)
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.get("/admin/api/activity")
def activity():
    if denied():
        return denied()
    return jsonify(events=admin_store.activity_log(request.args.get("q", "")))


@admin_bp.get("/admin/api/logs")
def production_logs():
    if denied():
        return denied()
    return jsonify(logs=admin_store.production_logs(request.args.get("q", ""), request.args.get("level", "")))


@admin_bp.get("/admin/api/inbox")
def inbox():
    if denied():
        return denied()
    try:
        result = list_messages()
    except InboxConfigurationError:
        return jsonify(error="Support mailbox is not configured."), 503
    except InboxUnavailableError:
        admin_store.log_event("ERROR", "Support mailbox inbox could not be loaded", request.remote_addr or "")
        return jsonify(error="Unable to load the support inbox right now."), 503
    audit("admin_inbox_listed")
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.get("/admin/api/inbox/<string:uid>")
def inbox_message(uid):
    if denied():
        return denied()
    try:
        result = read_message(uid)
    except ValueError:
        return jsonify(error="invalid inbox message ID"), 400
    except MessageTooLargeError as error:
        return jsonify(error=str(error)), 413
    except InboxConfigurationError:
        return jsonify(error="Support mailbox is not configured."), 503
    except InboxUnavailableError:
        admin_store.log_event("ERROR", "Support mailbox message could not be read", request.remote_addr or "")
        return jsonify(error="Unable to read this inbox message right now."), 503
    audit("admin_inbox_message_viewed")
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.get("/admin/api/settings")
def get_settings():
    if denied():
        return denied()
    values = admin_store.get_settings()
    return jsonify(company_cost_per_day=values.get("company_cost_per_day", COMPANY_COST_PER_DAY),
        company_cost_currency=values.get("company_cost_currency", COMPANY_COST_CURRENCY),
        activity_log_retention_days=values.get("activity_log_retention_days", ACTIVITY_LOG_RETENTION_DAYS),
        transcript_key_configured=bool(ADMIN_TRANSCRIPT_KEY),
        transcript_key_location="Set ADMIN_TRANSCRIPT_KEY in the project .env and recreate the Talkative container.")


@admin_bp.put("/admin/api/settings")
def update_settings():
    if denied():
        return denied()
    if not csrf_valid():
        return jsonify(error="invalid CSRF token"), 400
    data = request.get_json(silent=True) or {}
    if set(data) - {"company_cost_per_day", "company_cost_currency", "activity_log_retention_days"}:
        return jsonify(error="unsupported setting"), 400
    values = {}
    if "company_cost_per_day" in data:
        try:
            cost = float(data["company_cost_per_day"])
        except (TypeError, ValueError):
            return jsonify(error="daily cost must be a number"), 400
        if not math.isfinite(cost) or not 0 <= cost <= 1_000_000_000:
            return jsonify(error="invalid daily cost"), 400
        values["company_cost_per_day"] = cost
    if "company_cost_currency" in data:
        currency = str(data["company_cost_currency"]).upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            return jsonify(error="currency must be a 3-letter code"), 400
        values["company_cost_currency"] = currency
    if "activity_log_retention_days" in data:
        try:
            days = int(data["activity_log_retention_days"])
        except (TypeError, ValueError):
            return jsonify(error="retention must be whole days"), 400
        if not 1 <= days <= 180:
            return jsonify(error="retention must be 1-180 days"), 400
        values["activity_log_retention_days"] = days
    admin_store.set_settings(values)
    audit("admin_settings_updated")
    return jsonify(ok=True)