import os
import math
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
USER_DB = Path(os.getenv("USER_DATABASE_PATH", BASE_DIR / "users.db"))
ADMIN_DB = Path(os.getenv("ADMIN_DATABASE_PATH", BASE_DIR / "admin.db"))
LEGACY_DB = Path(os.getenv("DATABASE_PATH", BASE_DIR / "talkative.db"))
if not LEGACY_DB.exists() and LEGACY_DB.name == "talkative.db":
	previous_db = LEGACY_DB.with_name("stranger_chat.db")
	if previous_db.exists():
		LEGACY_DB = previous_db
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me")
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_TRANSCRIPT_KEY = os.getenv("ADMIN_TRANSCRIPT_KEY", "")
try:
	configured_rate = float(os.getenv("COMPANY_COST_PER_DAY", "0"))
	COMPANY_COST_PER_DAY = configured_rate if math.isfinite(configured_rate) and configured_rate >= 0 else 0.0
except ValueError:
	COMPANY_COST_PER_DAY = 0.0
configured_currency = os.getenv("COMPANY_COST_CURRENCY", "INR").strip().upper()
COMPANY_COST_CURRENCY = configured_currency if re.fullmatch(r"[A-Z]{3}", configured_currency) else "INR"
try:
    ACTIVITY_LOG_RETENTION_DAYS = max(1, min(180, int(os.getenv("ACTIVITY_LOG_RETENTION_DAYS", "30"))))
except ValueError:
    ACTIVITY_LOG_RETENTION_DAYS = 30
