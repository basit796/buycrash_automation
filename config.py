"""
config.py
---------
All constants for BuyCrash automation in one place.
"""
import os
import base64
from dotenv import load_dotenv

load_dotenv()

# ===================================================================
# ACCOUNTS
# 3 named accounts + 1 no-login slot (index 3)
# Set SITE_USERNAME_1/PASSWORD_B64_1 etc. in .env
# ===================================================================

def _load_accounts() -> list:
    accounts = []
    for i in range(1, 4):          # slots 1-3 only (4th = no-login)
        u = os.getenv(f"SITE_USERNAME_{i}", "").strip()
        p = os.getenv(f"PASSWORD_B64_{i}", "").strip()
        if u:
            accounts.append({"username": u, "password": p})
    # Fallback: legacy SITE_USERNAME / PASSWORD_B64
    if not accounts:
        u = os.getenv("SITE_USERNAME", "").strip()
        p = os.getenv("PASSWORD_B64", "").strip()
        if u:
            accounts.append({"username": u, "password": p})
    return accounts

ACCOUNTS = _load_accounts()

# Legacy single-account aliases (backward compat)
USERNAME     = ACCOUNTS[0]["username"] if ACCOUNTS else ""
PASSWORD_B64 = ACCOUNTS[0]["password"] if ACCOUNTS else ""

# ===================================================================
# SLOT CONFIG — 4 slots total
#   Slots 0-2 : ACCOUNTS[0], ACCOUNTS[1], ACCOUNTS[2]  (logged-in)
#   Slot    3 : NO-LOGIN (direct URL, no credentials)
# ===================================================================
TOTAL_SLOTS            = 4     # 3 accounts + 1 no-login
NO_LOGIN_SLOT          = 3     # index of the no-login slot
BATCH_SIZE             = 15    # reports per slot per cycle
INTER_BATCH_PAUSE_SEC  = 180   # 3 min pause between slots
LIMIT_PAUSE_SEC        = 300   # 5 min pause then skip to next slot on SEARCH_LIMIT_REACHED
OTP_WAIT_SEC           = 1800  # 30 min wait for OTP before moving to next account

# Pause when ALL 4 slots hit SEARCH_LIMIT_REACHED in the same cycle
ALL_SLOTS_LIMIT_PAUSE_SEC = 900  # 15 min

# ===================================================================
# RANDOM INTER-SEARCH DELAY (seconds)
# ===================================================================
SEARCH_DELAY_MIN = 15
SEARCH_DELAY_MAX = 35

# ===================================================================
# 2CAPTCHA
# ===================================================================
CAPTCHA_API_KEY  = os.getenv("CAPTCHA_API_KEY", "")
# Fallback site key — used when live extraction from the page fails
CAPTCHA_SITE_KEY = "6LcguussAAAAAJSH4sc2q8R_DnOSO-5qUXfLWjoE"

# ===================================================================
# URLS
# ===================================================================
BASE_URL        = "https://buycrash.lexisnexisrisk.com"
LOGIN_URL       = f"{BASE_URL}/login"
SEARCH_PAGE_URL = (
    f"{BASE_URL}/ui/report/search"
    f"?state=MI&jurisdiction=Detroit%20Police%20Department"
)
SEARCH_API_URL  = f"{BASE_URL}/search-svc/ssrqop/search"

# ===================================================================
# SEARCH SETTINGS
# ===================================================================
STATE        = "MI"
JURISDICTION = "Detroit Police Department"
START_REPORT = int(os.getenv("START_REPORT", "283746"))
TARGET_FOUND = int(os.getenv("TARGET_FOUND", "3"))

# ===================================================================
# REPORT TYPE MAPPING
# ===================================================================
REPORT_TYPE_MAP = {
    "A": "Accident Report",
    "F": "Fatal Accident Report",
    "H": "Hit and Run",
    "P": "Property Damage",
    "I": "Injury Report",
    "U": "Unknown",
}

def get_report_type_label(code: str) -> str:
    return REPORT_TYPE_MAP.get((code or "U").upper(), f"Type-{code}")

# ===================================================================
# GOOGLE SHEETS
# ===================================================================
SPREADSHEET_ID   = "1kn5uju5c2yh4PHHFAQDm-SRK3vDhCeEjLfdgDkFPZP8"
CREDENTIALS_FILE = "google_credentials.json"

SHEET_FOUND     = "Found"
SHEET_NOT_FOUND = "Not Found"
SHEET_ERRORS    = "Errors"
SHEET_START     = "Start Number"

# ===================================================================
# OUTPUT
# ===================================================================
OUTPUT_FILE   = "crash_reports.xlsx"
PROGRESS_FILE = "progress.txt"