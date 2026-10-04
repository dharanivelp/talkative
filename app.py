import os

from talkative_backend.application import create_app

if __name__ == "__main__":
    port = os.environ.get("PORT", "8000")
    os.execvp(
        "gunicorn",
        [
            "gunicorn",
            "--bind",
            f"0.0.0.0:{port}",
            "--workers",
            "2",
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
            "app:app",
        ],
    )
else:
    app = create_app()