import time

from flask import Flask, g, request

from talkative_backend.backend.admin import admin_bp
from talkative_backend.backend.auth import auth_bp
from talkative_backend.backend.chat import chat_bp
from talkative_backend.config import APP_ENV, BASE_DIR, SESSION_SECRET
from talkative_backend.planes import admin_store, redis_chat_store, user_store


def create_app(initialize=True):
    app = Flask(__name__, template_folder=str(BASE_DIR / "app/templates"), static_folder=str(BASE_DIR / "app/static"))
    app.secret_key = SESSION_SECRET
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

    @app.context_processor
    def inject_environment():
        return {"app_env": APP_ENV}

    @app.before_request
    def start_request_timer():
        g.request_started = time.perf_counter()

    @app.after_request
    def record_failed_request(response):
        if response.status_code >= 400:
            elapsed_ms = int((time.perf_counter() - getattr(g, "request_started", time.perf_counter())) * 1000)
            try:
                admin_store.log_event(
                    "ERROR" if response.status_code >= 500 else "WARNING",
                    f"{request.method} {request.path} returned {response.status_code} in {elapsed_ms}ms",
                    request.remote_addr or "",
                )
            except Exception:
                app.logger.exception("Failed to write a production error log")
        return response

    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(admin_bp)
    if initialize:
        user_store.init()
        admin_store.init()
        redis_chat_store.init()
    return app
