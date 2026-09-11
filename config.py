import os
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CREDENTIAL_KEY = os.getenv("CREDENTIAL_KEY", "").strip()

BASE_URL = "https://lms.bennett.edu.in"
CALENDAR_URL = "https://lms.bennett.edu.in/calendar/view.php"
CALENDAR_TIME = 1788975026

TIMEZONE = ZoneInfo("Asia/Kolkata")
SYNC_INTERVAL = 3600

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "college_reminder.db"
COOKIE_DIR = DATA_DIR / "cookies"
COOKIE_DIR.mkdir(exist_ok=True)
