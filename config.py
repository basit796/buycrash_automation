import os
import base64
from dotenv import load_dotenv

load_dotenv()

# --- Multi-Account Support ---
# Reads SITE_USERNAME_1/PASSWORD_B64_1, _2, _3 ... from .env
# Skips any slot where username is empty.
def _load_accounts() -> list:
    accounts = []
    for i in range(1, 10):  # supports up to 9 accounts
        u = os.getenv(f"SITE_USERNAME_{i}", "").strip()
        p = os.getenv(f"PASSWORD_B64_{i}", "").strip()
        if u:
            accounts.append({"username": u, "password": p})
    # Fallback: legacy SITE_USERNAME / PASSWORD_B64 keys
    if not accounts:
        u = os.getenv("SITE_USERNAME", "").strip()
        p = os.getenv("PASSWORD_B64", "").strip()
        if u:
            accounts.append({"username": u, "password": p})
    return accounts

ACCOUNTS = _load_accounts()

# Legacy single-account aliases (still work for old code)
USERNAME     = ACCOUNTS[0]["username"] if ACCOUNTS else ""
PASSWORD_B64 = ACCOUNTS[0]["password"] if ACCOUNTS else ""

def get_password():
    return PASSWORD_B64

# --- 2Captcha ---
CAPTCHA_API_KEY  = os.getenv("CAPTCHA_API_KEY", "")
CAPTCHA_SITE_KEY = "6LcguussAAAAAJSH4sc2q8R_DnOSO-5qUXfLWjoE"

# --- URLs ---
BASE_URL        = "https://buycrash.lexisnexisrisk.com"
LOGIN_URL       = f"{BASE_URL}/login"
SEARCH_PAGE_URL = (f"{BASE_URL}/ui/report/search"
                   f"?state=MI&jurisdiction=Detroit%20Police%20Department")
SEARCH_API_URL  = f"{BASE_URL}/search-svc/ssrqop/search"

# --- Search Settings ---
STATE        = "MI"
JURISDICTION = "Detroit Police Department"
START_REPORT = int(os.getenv("START_REPORT", "283746"))
TARGET_FOUND = int(os.getenv("TARGET_FOUND", "3"))

# --- Report Type Mapping ---
REPORT_TYPE_MAP = {
    "A": "Accident Report",
    "F": "Fatal Accident Report",
    "H": "Hit and Run",
    "P": "Property Damage",
    "I": "Injury Report",
    "U": "Unknown",
}

def get_report_type_label(code: str) -> str:
    return REPORT_TYPE_MAP.get(code.upper(), f"Type-{code}")

# --- Output ---
OUTPUT_FILE   = "crash_reports.xlsx"
PROGRESS_FILE = "progress.txt"