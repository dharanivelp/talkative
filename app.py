import os
import sys

from talkative_backend.application import create_app

if __name__ == "__main__":
    port = os.environ.get("PORT", "8000")
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
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