import hashlib
import hmac
import json
import logging
import re
import secrets
import sqlite3
from datetime import datetime, timezone

import pycountry
from flask import Blueprint, Response, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from talkative_backend.config import APP_ENV, PUBLIC_SITE_URL, SESSION_SECRET
from talkative_backend.core.functions import PASSWORD_REQUIREMENTS, age_category, audit, current_user, is_eligible, is_strong_password, parse_dob, public_profile_details, timestamp
from talkative_backend.emailer import EmailConfigurationError, EmailDeliveryError, send_otp_email
from talkative_backend.planes import admin_store, user_store
from talkative_backend.planes import sqlite_chat_store as chat_store

auth_bp = Blueprint("auth", __name__)
TERMS_VERSION = "2026-10-04"
logger = logging.getLogger(__name__)
SIGNUP_OTP_TTL = 120
SIGNUP_OTP_MAX_ATTEMPTS = 5
OTP_SEND_EMAIL_LIMIT = 5
OTP_SEND_WINDOW_SECONDS = 3600
OTP_SEND_STRIKE_TTL = 30 * 24 * 3600
OTP_SEND_LOCK_KEY_PREFIX = f"{chat_store.PREFIX}otp-send-lock"
OTP_SEND_STRIKE_KEY_PREFIX = f"{chat_store.PREFIX}otp-send-strikes"
PROFILE_EDUCATION_GROUPS = {
    "School and secondary": (
        "No formal education",
        "SSLC",
        "SSC",
        "HSC",
        "CBSE Class 10",
        "CBSE Class 12",
        "GCSE",
        "IGCSE",
        "O-Level",
        "A-Level",
        "IB Middle Years Programme",
        "IB Diploma Programme",
        "High School Diploma",
        "GED",
        "Abitur",
        "Baccalaureate",
        "Matura",
        "Leaving Certificate",
        "Senior Secondary Certificate",
        "WAEC SSCE",
        "KCSE",
        "ATAR",
    ),
    "Vocational and certificates": (
        "Certificate",
        "Advanced Certificate",
        "Trade Certificate",
        "ITI",
        "Apprenticeship",
        "NVQ",
        "BTEC",
        "TAFE Certificate I",
        "TAFE Certificate II",
        "TAFE Certificate III",
        "TAFE Certificate IV",
        "Diploma",
        "Advanced Diploma",
        "Higher National Certificate (HNC)",
        "Higher National Diploma (HND)",
        "Foundation Degree",
        "Postgraduate Certificate",
        "Postgraduate Diploma",
        "PGCE",
        "PGDM",
        "PGDBA",
    ),
    "Undergraduate": (
        "Associate",
        "Associate degree",
        "Associate of Arts (AA)",
        "Associate of Science (AS)",
        "Associate of Applied Science (AAS)",
        "Bachelor's",
        "Bachelor's degree",
        "B.A.",
        "B.Sc.",
        "B.S.",
        "B.Com.",
        "B.B.A.",
        "B.C.A.",
        "B.E.",
        "B.Tech.",
        "B.Eng.",
        "B.Arch.",
        "B.Des.",
        "B.Ed.",
        "B.F.A.",
        "B.Mus.",
        "B.S.W.",
        "B.Sc.N.",
        "B.Pharm.",
        "LL.B.",
        "MBBS",
        "BDS",
        "B.V.Sc.",
        "B.Sc. (Hons)",
        "Bachelor of Applied Science",
        "Bachelor of Laws",
    ),
    "Postgraduate": (
        "Master's",
        "Master's degree",
        "M.A.",
        "M.Sc.",
        "M.S.",
        "M.Com.",
        "M.B.A.",
        "M.C.A.",
        "M.E.",
        "M.Tech.",
        "M.Eng.",
        "M.Arch.",
        "M.Des.",
        "M.Ed.",
        "M.F.A.",
        "M.S.W.",
        "M.P.H.",
        "M.Pharm.",
        "LL.M.",
        "M.D.",
        "M.S. (Medicine)",
        "M.Phil.",
        "Master of Research (M.Res.)",
        "Master of Public Administration (MPA)",
        "Master of Public Policy (MPP)",
        "Master of Laws",
        "Master of Education",
        "Master of Engineering",
        "Master of Technology",
    ),
    "Doctoral and research": (
        "Doctorate",
        "Ph.D.",
        "D.Phil.",
        "Ed.D.",
        "D.B.A.",
        "Eng.D.",
        "D.Sc.",
        "D.Litt.",
        "J.D.",
        "Pharm.D.",
        "D.V.M.",
        "D.D.S.",
        "M.D. (Doctor of Medicine)",
    ),
    "Other": (
        "Other",
    ),
}
PROFILE_EDUCATION_OPTIONS = tuple(
    option
    for options in PROFILE_EDUCATION_GROUPS.values()
    for option in options
)
SIGNUP_OTP_GENERIC_RESPONSE = {
    "ok": True,
    "message": "Enter the verification code to continue.",
}
DEVELOPMENT_SIGNUP_OTP = "123456"
SIGNUP_OTP_IP_LIMIT = 20
SIGNUP_OTP_RATE_LIMIT_PREFIX = f"{chat_store.PREFIX}signup-otp-rate-v2"


def _email_key(email):
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def _location_options(country_code):
    subdivisions = [
        {"code": subdivision.code, "name": subdivision.name}
        for subdivision in pycountry.subdivisions
        if subdivision.country_code == country_code
    ]
    return sorted(subdivisions, key=lambda subdivision: subdivision["name"].casefold())


def _otp_digest(email, code):
    return hmac.new(SESSION_SECRET.encode("utf-8"), f"{email}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def _login_otp_digest(challenge_id, code):
    return hmac.new(SESSION_SECRET.encode("utf-8"), f"{challenge_id}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def _forgot_password_key(email):
    return f"{chat_store.PREFIX}forgot-password:{_email_key(email)}"


def _increment_limiter(key, limit, window):
    client = chat_store.client
    count = client.incr(key)
    if count == 1:
        client.expire(key, window)
    return count <= limit


def _apply_signup_rate_limits(email):
    ip_digest = hashlib.sha256((request.remote_addr or "unknown").encode("utf-8")).hexdigest()
    if not _increment_limiter(
        f"{SIGNUP_OTP_RATE_LIMIT_PREFIX}:ip:{ip_digest}", SIGNUP_OTP_IP_LIMIT, 3600
    ):
        return False
    return True


def _otp_email_rate_limit(email):
    email_digest = _email_key(email)
    lock_key = f"{OTP_SEND_LOCK_KEY_PREFIX}:{email_digest}"
    active_lock = chat_store.client.get(lock_key)
    if active_lock:
        return max(1, int(active_lock) - int(datetime.now(timezone.utc).timestamp()))

    count_key = f"{chat_store.PREFIX}otp-send-count:{email_digest}"
    count = chat_store.client.incr(count_key)
    if count == 1:
        chat_store.client.expire(count_key, OTP_SEND_WINDOW_SECONDS)
    if count <= OTP_SEND_EMAIL_LIMIT:
        return 0

    strike_key = f"{OTP_SEND_STRIKE_KEY_PREFIX}:{email_digest}"
    strikes = chat_store.client.incr(strike_key)
    if strikes == 1:
        chat_store.client.expire(strike_key, OTP_SEND_STRIKE_TTL)
    lock_seconds = 3600 if strikes == 1 else 86400
    expires_at = int(datetime.now(timezone.utc).timestamp()) + lock_seconds
    chat_store.client.set(lock_key, str(expires_at), ex=lock_seconds)
    return lock_seconds


def _otp_rate_limited_response(retry_after):
    hours = max(1, (retry_after + 3599) // 3600)
    period = "1 hour" if hours == 1 else "1 day"
    response = jsonify(
        error=f"Too many verification requests. Try again in {period}.",
        retry_after=retry_after,
    )
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    return response


def _send_signup_otp(email, payload=None):
    if APP_ENV not in {"development", "production"}:
        return jsonify(error="Email verification is not configured for this environment."), 503
    if user_store.by_email(email):
        return jsonify(error="An account with this email already exists. Log in or use a different email."), 409

    email_digest = _email_key(email)
    state_key = f"{chat_store.PREFIX}signup-otp:{email_digest}"
    cooldown_key = f"{state_key}:cooldown"
    if not chat_store.client.set(cooldown_key, "1", nx=True, ex=60):
        response = jsonify(error="Please wait before requesting another code.", retry_after=60)
        response.status_code = 429
        response.headers["Retry-After"] = "60"
        return response, 429
    if not _apply_signup_rate_limits(email):
        chat_store.client.delete(cooldown_key)
        return jsonify(error="Too many verification requests. Try again later."), 429
    retry_after = _otp_email_rate_limit(email)
    if retry_after:
        chat_store.client.delete(cooldown_key)
        return _otp_rate_limited_response(retry_after), 429
    code = DEVELOPMENT_SIGNUP_OTP if APP_ENV == "development" else f"{secrets.randbelow(1_000_000):06}"
    state = {
        "otp_hash": _otp_digest(email, code),
        "payload": json.dumps(payload or {}),
        "attempts": "0",
    }
    try:
        chat_store.client.hset(state_key, mapping=state)
        chat_store.client.expire(state_key, SIGNUP_OTP_TTL)
    except sqlite3.Error:
        chat_store.client.delete(state_key, cooldown_key)
        logger.exception("Signup verification state could not be stored")
        return jsonify(error="Unable to start verification right now. Try again later."), 503
    if APP_ENV == "production":
        try:
            send_otp_email(email, code, "signup")
        except (EmailConfigurationError, EmailDeliveryError):
            try:
                chat_store.client.delete(state_key, cooldown_key)
            except sqlite3.Error:
                logger.exception("Failed to clear signup verification state after email failure")
            logger.exception("Signup verification email could not be sent")
            return jsonify(error="Unable to send the verification email right now. Try again later."), 503
    return jsonify(**SIGNUP_OTP_GENERIC_RESPONSE), 200


def close_user_activity(user_id):
    chat_store.leave_queue(user_id)
    active_session = chat_store.client.get(f"{chat_store.PREFIX}user-session:{user_id}")
    if active_session:
        ended = chat_store.end_session(active_session, user_id, timestamp())
        if ended:
            for participant in (ended["user_a"], ended["user_b"]):
                if participant != user_id:
                    user_store.update_score(participant, seconds=ended["duration_seconds"])
            admin_store.finish_session(active_session, ended["ended_at"], ended["duration_seconds"], ended["transcript"])
            chat_store.cleanup_ended(active_session)
            audit("chat_ended", user_id, active_session)
    chat_store.remove_presence(user_id)


@auth_bp.get("/")
def home():
    countries = [{"code": country.alpha_2, "name": country.name} for country in pycountry.countries]
    countries.sort(key=lambda country: country["name"])
    return render_template("index.html", countries=countries)


@auth_bp.get("/account")
def account_page():
    if not current_user():
        return redirect("/")
    return render_template("account.html")


@auth_bp.get("/terms")
def terms_page():
    return render_template("terms.html")


@auth_bp.get("/privacy")
def privacy_page():
    return render_template("privacy.html")


@auth_bp.get("/robots.txt")
def robots_txt():
    if APP_ENV != "production":
        body = "User-agent: *\nDisallow: /\n"
    else:
        body = (
            "User-agent: *\n"
            "Disallow: /account\n"
            "Disallow: /admin\n"
            "Disallow: /api/\n"
            f"Sitemap: {PUBLIC_SITE_URL}/sitemap.xml\n"
        )
    return Response(body, mimetype="text/plain")


@auth_bp.get("/sitemap.xml")
def sitemap_xml():
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{PUBLIC_SITE_URL}/</loc></url>"
        f"<url><loc>{PUBLIC_SITE_URL}/terms</loc></url>"
        f"<url><loc>{PUBLIC_SITE_URL}/privacy</loc></url>"
        "</urlset>"
    )
    return Response(body, mimetype="application/xml")


@auth_bp.post("/api/auth/signup")
def signup():
    data = request.get_json(silent=True) or {}
    allowed_fields = {
        "terms_accepted", "email", "password", "first_name",
        "last_name", "gender", "country_code", "date_of_birth",
    }
    if set(data) - allowed_fields:
        return jsonify(error="Unsupported signup field"), 400
    if data.get("terms_accepted") is not True:
        return jsonify(error="You must agree to the Terms and Conditions and Privacy Policy"), 400
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    first_name = str(data.get("first_name", "")).strip()
    last_name = str(data.get("last_name", "")).strip()
    name = f"{first_name} {last_name}".strip()
    gender = str(data.get("gender", ""))
    country_code = str(data.get("country_code", "")).strip().upper()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify(error="Enter a valid email address"), 400
    try:
        if user_store.by_email(email):
            return jsonify(error="An account with this email already exists. Log in or use a different email."), 409
    except sqlite3.Error:
        logger.exception("Signup verification request failed")
        return jsonify(error="Unable to start signup verification right now."), 503
    if not first_name or len(first_name) > 60 or not last_name or len(last_name) > 60 or len(name) > 120:
        return jsonify(error="Enter first and last names up to 60 characters each"), 400
    if not is_strong_password(password):
        return jsonify(error=PASSWORD_REQUIREMENTS), 400
    if gender not in {"male", "female", "non_binary", "prefer_not_to_say"}:
        return jsonify(error="Select a valid gender"), 400
    if not pycountry.countries.get(alpha_2=country_code):
        return jsonify(error="Select a valid country"), 400
    try:
        dob = parse_dob(data.get("date_of_birth", ""))
    except (TypeError, ValueError):
        return jsonify(error="Enter a valid date of birth"), 400
    if not is_eligible(dob):
        return jsonify(error="You must be at least 18 years old to create an account."), 403
    try:
        result, status = _send_signup_otp(email, {
            "email": email,
            "password_hash": generate_password_hash(password),
            "first_name": first_name,
            "last_name": last_name,
            "dob": dob.isoformat(),
            "gender": gender,
            "country_code": country_code,
            "terms_accepted_at": timestamp(),
        })
        if status == 200:
            audit("signup_otp_requested")
        return result, status
    except sqlite3.Error:
        logger.exception("Signup verification request failed")
        return jsonify(error="Unable to start signup verification right now."), 503


@auth_bp.get("/api/auth/username-availability")
def username_availability():
    username = request.args.get("username", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,23}", username):
        return jsonify(available=False, message="Use 3-24 letters, numbers, dots, dashes, or underscores.")
    try:
        existing = user_store.by_username(username)
        user = current_user()
        available = existing is None or (user is not None and existing["user_id"] == user["user_id"])
    except sqlite3.Error:
        logger.exception("Username availability check failed")
        return jsonify(error="Unable to check username availability right now."), 503
    return jsonify(
        available=available,
        message="Username is available." if available else "Username is already taken.",
    )


@auth_bp.post("/api/auth/resend-signup-otp")
def resend_signup_otp():
    email = str((request.get_json(silent=True) or {}).get("email", "")).strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify(error="Enter a valid email address"), 400
    state_key = f"{chat_store.PREFIX}signup-otp:{_email_key(email)}"
    try:
        raw_payload = chat_store.client.hget(state_key, "payload")
        if not raw_payload:
            return jsonify(**SIGNUP_OTP_GENERIC_RESPONSE)
        result, status = _send_signup_otp(email, json.loads(raw_payload))
        if status == 200:
            audit("signup_otp_resent")
        return result, status
    except (sqlite3.Error, TypeError, ValueError):
        logger.exception("Signup verification resend failed")
        return jsonify(error="Unable to resend a verification email right now."), 503


@auth_bp.post("/api/auth/verify-signup-email")
def verify_signup_email():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    code = str(data.get("code", "")).strip()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or not re.fullmatch(r"\d{6}", code):
        return jsonify(error="Enter the six-digit code sent to your email."), 400
    state_key = f"{chat_store.PREFIX}signup-otp:{_email_key(email)}"
    try:
        pending_json = chat_store.client.hget(state_key, "payload")
    except sqlite3.Error:
        logger.exception("Signup verification check failed")
        return jsonify(error="Unable to verify the code right now."), 503
    if not pending_json:
        return jsonify(error="This signup verification expired. Go back and submit signup again for a new code."), 400
    try:
        payload = json.loads(pending_json)
    except (TypeError, ValueError):
        logger.error("Signup verification state is invalid")
        return jsonify(error="Unable to verify the code right now."), 503
    signup_token = None
    verified_key = None
    if not payload.get("admin_created"):
        signup_token = secrets.token_urlsafe(32)
        verified_key = f"{chat_store.PREFIX}signup-verified:{_email_key(signup_token)}"
    try:
        result = chat_store.client.verify_challenge(
            state_key,
            _otp_digest(email, code),
            SIGNUP_OTP_MAX_ATTEMPTS,
            verified_key=verified_key,
            ttl_seconds=SIGNUP_OTP_TTL if verified_key else None,
        )
    except sqlite3.Error:
        logger.exception("Signup verification check failed")
        return jsonify(error="Unable to verify the code right now."), 503
    if int(result[0]) == 0:
        return jsonify(error="This signup verification expired. Go back and submit signup again for a new code."), 400
    if int(result[0]) != 1:
        return jsonify(error="The verification code is incorrect. Try again."), 400
    if signup_token:
        audit("signup_email_verified")
        return jsonify(ok=True, signup_token=signup_token)
    return _create_verified_user(payload, payload["username"], admin_created=True)


def _create_verified_user(payload, username, admin_created=False):
    try:
        user_id = user_store.create_user(
            payload["email"], username, payload["password_hash"],
            payload["first_name"], payload["last_name"], payload["dob"],
            payload["gender"], payload["country_code"], timestamp(),
            TERMS_VERSION, payload["terms_accepted_at"],
            password_reset_required=payload.get("password_reset_required", False),
        )
    except sqlite3.IntegrityError:
        return jsonify(error="Email or username is already in use. Check the details and try again."), 409
    session.clear()
    password_reset_required = bool(payload.get("password_reset_required", False))
    session.update(role="password_reset" if password_reset_required else "user", user_id=user_id)
    audit("admin_user_created" if admin_created else "account_created", user_id)
    return jsonify(ok=True, password_reset_required=password_reset_required)


@auth_bp.post("/api/auth/complete-signup")
def complete_signup():
    data = request.get_json(silent=True) or {}
    signup_token = str(data.get("signup_token", "")).strip()
    username = str(data.get("username", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,60}", signup_token):
        return jsonify(error="Email verification has expired. Start signup again."), 400
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,23}", username):
        return jsonify(error="Username must be 3-24 characters using letters, numbers, dots, dashes, or underscores"), 400
    verified_key = f"{chat_store.PREFIX}signup-verified:{_email_key(signup_token)}"
    try:
        payload_json = chat_store.client.get(verified_key)
        if not payload_json:
            return jsonify(error="Email verification has expired. Start signup again."), 400
        payload = json.loads(payload_json)
        if user_store.by_email(payload["email"]):
            return jsonify(error="An account with this email already exists. Log in or use a different email."), 409
        if user_store.by_username(username):
            return jsonify(error="That username is already taken."), 409
        result = _create_verified_user(payload, username)
        if isinstance(result, tuple):
            return result
        chat_store.client.delete(verified_key)
        return result
    except (sqlite3.Error, TypeError, ValueError, KeyError):
        logger.exception("Verified signup could not be completed")
        return jsonify(error="Unable to create your account right now."), 503


@auth_bp.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    user = user_store.by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        audit("login_failed")
        return jsonify(error="Invalid email or password"), 401
    if user["admin_blocked"]:
        audit("login_blocked_account", user["user_id"])
        return jsonify(error="This account has been blocked. Contact support."), 403
    if APP_ENV not in {"development", "production"}:
        return jsonify(error="Login verification is not configured for this environment."), 503
    user_id = user["user_id"]
    ip_digest = hashlib.sha256((request.remote_addr or "unknown").encode("utf-8")).hexdigest()
    cooldown_key = f"{chat_store.PREFIX}login-otp-cooldown:{_email_key(email)}"
    try:
        if not _increment_limiter(f"{chat_store.PREFIX}login-otp:ip:{ip_digest}", 10, 3600):
            return jsonify(error="Too many verification requests. Try again later."), 429
        if not chat_store.client.set(cooldown_key, "1", nx=True, ex=60):
            response = jsonify(error="Please wait before requesting another code.", retry_after=60)
            response.status_code = 429
            response.headers["Retry-After"] = "60"
            return response
        retry_after = _otp_email_rate_limit(email)
        if retry_after:
            chat_store.client.delete(cooldown_key)
            return _otp_rate_limited_response(retry_after)
        challenge_id = secrets.token_urlsafe(32)
        code = DEVELOPMENT_SIGNUP_OTP if APP_ENV == "development" else f"{secrets.randbelow(1_000_000):06}"
        key = f"{chat_store.PREFIX}login-otp:{_email_key(challenge_id)}"
        chat_store.client.hset(key, mapping={
            "otp_hash": _login_otp_digest(challenge_id, code),
            "payload": json.dumps({
                "user_id": user_id,
                "password_reset_required": bool(user["password_reset_required"]),
            }),
            "attempts": "0",
        })
        chat_store.client.expire(key, SIGNUP_OTP_TTL)
    except sqlite3.Error:
        try:
            chat_store.client.delete(cooldown_key)
        except sqlite3.Error:
            logger.exception("Failed to clear login verification cooldown")
        logger.exception("Login verification state could not be stored")
        return jsonify(error="Unable to start login verification right now."), 503
    if APP_ENV == "production":
        try:
            send_otp_email(email, code, "login")
        except (EmailConfigurationError, EmailDeliveryError):
            try:
                chat_store.client.delete(key, cooldown_key)
            except sqlite3.Error:
                logger.exception("Failed to clear login verification state after email failure")
            logger.exception("Login verification email could not be sent")
            return jsonify(error="Unable to send the verification email right now. Try again later."), 503
    audit("login_otp_requested", user_id)
    return jsonify(
        ok=True,
        otp_required=True,
        challenge_id=challenge_id,
        message="Enter the verification code to continue.",
    )


@auth_bp.post("/api/auth/forgot-password")
def forgot_password():
    email = str((request.get_json(silent=True) or {}).get("email", "")).strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify(error="Enter a valid email address"), 400
    if APP_ENV not in {"development", "production"}:
        return jsonify(error="Password reset is not configured for this environment."), 503

    ip_digest = hashlib.sha256((request.remote_addr or "unknown").encode("utf-8")).hexdigest()
    try:
        if not _increment_limiter(f"{chat_store.PREFIX}forgot-password:ip:{ip_digest}", 10, 3600):
            return jsonify(error="Too many requests. Try again later."), 429
        user = user_store.by_email(email)
        if user:
            state_key = _forgot_password_key(email)
            cooldown_key = f"{state_key}:cooldown"
            if not chat_store.client.set(cooldown_key, "1", nx=True, ex=60):
                return jsonify(
                    ok=True,
                    message="If an account exists for that email, a verification code has been sent.",
                )
            retry_after = _otp_email_rate_limit(email)
            if retry_after:
                chat_store.client.delete(cooldown_key)
                return _otp_rate_limited_response(retry_after)
            code = DEVELOPMENT_SIGNUP_OTP if APP_ENV == "development" else f"{secrets.randbelow(1_000_000):06}"
            chat_store.client.hset(state_key, mapping={
                "otp_hash": _otp_digest(email, code),
                "payload": json.dumps({"user_id": user["user_id"]}),
                "attempts": "0",
            })
            chat_store.client.expire(state_key, SIGNUP_OTP_TTL)
            if APP_ENV == "production":
                try:
                    send_otp_email(email, code, "password reset")
                except (EmailConfigurationError, EmailDeliveryError):
                    try:
                        chat_store.client.delete(state_key, cooldown_key)
                    except sqlite3.Error:
                        logger.exception("Failed to clear password-reset state after email failure")
                    logger.exception("Password-reset verification email could not be sent")
                    return jsonify(error="Unable to send the verification email right now. Try again later."), 503
    except sqlite3.Error:
        logger.exception("Password-reset verification request failed")
        return jsonify(error="Unable to start password reset right now."), 503
    audit("password_reset_requested")
    return jsonify(ok=True, message="If an account exists for that email, a verification code has been sent.")


@auth_bp.post("/api/auth/reset-password")
def reset_password():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    code = str(data.get("code", "")).strip()
    new_password = str(data.get("new_password", ""))
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify(error="Enter a valid email address"), 400
    if not re.fullmatch(r"\d{6}", code):
        return jsonify(error="Enter the six-digit verification code."), 400
    if not is_strong_password(new_password):
        return jsonify(error=PASSWORD_REQUIREMENTS), 400

    try:
        result = chat_store.client.verify_challenge(
            _forgot_password_key(email),
            _otp_digest(email, code),
            SIGNUP_OTP_MAX_ATTEMPTS,
        )
    except sqlite3.Error:
        logger.exception("Password-reset verification failed")
        return jsonify(error="Unable to verify the code right now."), 503
    if int(result[0]) != 1:
        return jsonify(error="The code is invalid or expired. Request a new code and try again."), 400
    try:
        payload = json.loads(result[1])
        user = user_store.by_user_id(payload["user_id"])
        if not user or user["email"].lower() != email:
            return jsonify(error="The code is invalid or expired. Request a new code and try again."), 400
        user_store.update_password(user["user_id"], generate_password_hash(new_password))
        audit("password_reset_completed", user["user_id"])
    except (sqlite3.Error, TypeError, ValueError, KeyError):
        logger.exception("Password reset could not be completed")
        return jsonify(error="Unable to reset your password right now."), 503
    return jsonify(ok=True, message="Password updated. You can now log in.")


@auth_bp.post("/api/auth/verify-login-otp")
def verify_login_otp():
    data = request.get_json(silent=True) or {}
    challenge_id = str(data.get("challenge_id", "")).strip()
    code = str(data.get("code", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,60}", challenge_id) or not re.fullmatch(r"\d{6}", code):
        return jsonify(error="Enter the six-digit verification code."), 400
    key = f"{chat_store.PREFIX}login-otp:{_email_key(challenge_id)}"
    try:
        result = chat_store.client.verify_challenge(
            key, _login_otp_digest(challenge_id, code), SIGNUP_OTP_MAX_ATTEMPTS
        )
    except sqlite3.Error:
        logger.exception("Login verification check failed")
        return jsonify(error="Unable to verify the code right now."), 503
    if int(result[0]) != 1:
        return jsonify(error="The code is invalid or expired. Try logging in again."), 400
    try:
        payload = json.loads(result[1])
    except (TypeError, ValueError):
        logger.error("Login verification state is invalid")
        return jsonify(error="Unable to verify the code right now."), 503
    session.clear()
    user_id = payload["user_id"]
    password_reset_required = bool(payload["password_reset_required"])
    session.update(role="password_reset" if password_reset_required else "user", user_id=user_id)
    audit("login_succeeded", user_id)
    return jsonify(ok=True, password_reset_required=password_reset_required)


@auth_bp.post("/api/auth/complete-password-reset")
def complete_password_reset():
    user_id = session.get("user_id")
    if session.get("role") != "password_reset" or not user_id:
        return jsonify(error="password reset not required"), 401
    user = user_store.by_user_id(user_id)
    if not user or not user["password_reset_required"] or user["admin_blocked"]:
        session.clear()
        return jsonify(error="password reset is no longer valid"), 401
    new_password = str((request.get_json(silent=True) or {}).get("new_password", ""))
    if not is_strong_password(new_password):
        return jsonify(error=PASSWORD_REQUIREMENTS), 400
    user_store.update_password(user_id, generate_password_hash(new_password))
    session.clear()
    session.update(role="user", user_id=user_id)
    audit("admin_password_reset_completed", user_id)
    return jsonify(ok=True)


@auth_bp.post("/api/logout")
def logout():
    user = current_user()
    if user:
        close_user_activity(user["user_id"])
        audit("logout", user["user_id"])
    session.clear()
    return jsonify(ok=True)


@auth_bp.get("/api/me")
def me():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    country = pycountry.countries.get(alpha_2=user["country_code"])
    participant_view = {"name": user["first_name"], "age_category": age_category(parse_dob(user["date_of_birth"])), "gender": user["gender"], "score": user["quality_score"], "streak_days": user["current_streak_days"], "country_code": user["country_code"], "country_name": country.name if country else ""}
    participant_view.update(public_profile_details(user))
    return jsonify(name=user["name"], first_name=user["first_name"], last_name=user["last_name"], username=user["username"], email=user["email"],
                   date_of_birth=user["date_of_birth"], gender=user["gender"],
                   country_code=user["country_code"], country_name=country.name if country else "",
                   bio=user["bio"], profession=user["profession"], education=user["education"], location=user["location"],
                   location_options=_location_options(user["country_code"]),
                   education_groups=PROFILE_EDUCATION_GROUPS,
                   show_bio=bool(user["show_bio"]), show_profession=bool(user["show_profession"]), show_education=bool(user["show_education"]), show_location=bool(user["show_location"]), participant_view=participant_view,
                   score=user["quality_score"], streak_days=user["current_streak_days"], complete=True)


@auth_bp.post("/api/profile")
def update_profile():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    data = request.get_json(silent=True) or {}
    profile_fields = {"bio", "profession", "education", "location"}
    visibility_fields = {f"show_{field}" for field in profile_fields}
    if set(data) - ({"username"} | profile_fields | visibility_fields):
        return jsonify(error="Unsupported profile field"), 400
    username = str(data.get("username", user["username"])).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,23}", username):
        return jsonify(error="Username must be 3-24 characters using letters, numbers, dots, dashes, or underscores"), 400
    existing = user_store.by_username(username)
    if existing and existing["user_id"] != user["user_id"]:
        return jsonify(error="That username is already taken"), 409
    limits = {"bio": 32, "profession": 32, "education": 100, "location": 120}
    values = {}
    for field, limit in limits.items():
        value = data.get(field, user[field])
        if not isinstance(value, str):
            return jsonify(error=f"{field.title()} must be text"), 400
        value = value.strip()
        if len(value) > limit:
            return jsonify(error=f"{field.title()} must be {limit} characters or fewer"), 400
        values[field] = value
    if values["education"] and values["education"] not in PROFILE_EDUCATION_OPTIONS:
        return jsonify(error="Choose an education level from the available options"), 400
    if values["location"] and values["location"] != user["location"]:
        allowed_locations = {option["name"] for option in _location_options(user["country_code"])}
        if values["location"] not in allowed_locations:
            return jsonify(error="Location must be a state or region in your country"), 400
    visibility = {}
    for field in profile_fields:
        key = f"show_{field}"
        value = data.get(key, bool(user[key]))
        if not isinstance(value, bool):
            return jsonify(error=f"{key.replace('_', ' ').title()} must be true or false"), 400
        visibility[key] = value
    user_store.update_profile(user["user_id"], username, values["bio"], values["profession"], values["education"], values["location"], visibility["show_bio"], visibility["show_profession"], visibility["show_education"], visibility["show_location"])
    audit("profile_updated", user["user_id"])
    return jsonify(ok=True)


@auth_bp.post("/api/password")
def update_password():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    data = request.get_json(silent=True) or {}
    current_password = str(data.get("current_password", ""))
    new_password = str(data.get("new_password", ""))
    if not check_password_hash(user["password_hash"], current_password):
        return jsonify(error="Current password is incorrect"), 400
    if not is_strong_password(new_password):
        return jsonify(error=PASSWORD_REQUIREMENTS), 400
    user_store.update_password(user["user_id"], generate_password_hash(new_password))
    audit("password_changed", user["user_id"])
    return jsonify(ok=True)


@auth_bp.post("/api/presence")
def presence():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    active_day = datetime.now(timezone.utc).date().isoformat()
    streak_days = user_store.record_active_day(user["user_id"], active_day)
    return jsonify(online=chat_store.touch_presence(user["user_id"]), streak_days=streak_days)


@auth_bp.get("/api/online")
def online():
    if not current_user():
        return jsonify(error="login required"), 401
    return jsonify(online=chat_store.online_count())


@auth_bp.delete("/api/account")
def delete_account():
    user = current_user()
    if not user:
        return jsonify(error="login required"), 401
    user_id = user["user_id"]
    close_user_activity(user_id)
    audit("account_deleted", user_id)
    user_store.delete_user(user_id)
    session.clear()
    return jsonify(ok=True)
