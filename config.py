"""
config.py
---------
Minimal hardcoded config — only things that can't come from the sheet.
Everything else (accounts, target, email, OTP timeout) lives in the
"Config" tab of Google Sheets and is loaded at runtime by sheets_handler.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ===================================================================
# MUST be in .env — needed before we can even connect to the sheet
# ===================================================================
CAPTCHA_API_KEY  = os.getenv("CAPTCHA_API_KEY", "")
SPREADSHEET_ID   = os.getenv("SPREADSHEET_ID", "1kn5uju5c2yh4PHHFAQDm-SRK3vDhCeEjLfdgDkFPZP8")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "google_credentials.json")

# ===================================================================
# CAPTCHA — site key fallback (live key extracted from page at runtime)
# ===================================================================
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

# ===================================================================
# SLOT / ROTATION CONSTANTS
# ===================================================================
TOTAL_SLOTS               = 4      # 3 accounts + 1 no-login
NO_LOGIN_SLOT             = 3
BATCH_SIZE                = 15     # reports per slot
INTER_BATCH_PAUSE_SEC     = 180    # 3 min between slots
LIMIT_PAUSE_SEC           = 300    # 5 min on SEARCH_LIMIT_REACHED per slot
ALL_SLOTS_LIMIT_PAUSE_SEC = 900    # 15 min when all 4 slots hit limit
RESTART_PAUSE_SEC         = 120    # 2 min pause on "restart" control command
CONSECUTIVE_ERROR_LIMIT   = 20     # stop script after N back-to-back errors

# ===================================================================
# RANDOM INTER-SEARCH DELAY (seconds)
# ===================================================================
SEARCH_DELAY_MIN = 15
SEARCH_DELAY_MAX = 35

# ===================================================================
# SHEET TAB NAMES
# ===================================================================
SHEET_FOUND      = "Found"
SHEET_NOT_FOUND  = "Not Found"
SHEET_ERRORS     = "Errors"
SHEET_START      = "Start Number"
SHEET_CONFIG     = "Config"

# ===================================================================
# CONFIG SHEET ROW MAPPING  (row index, 1-based, column B = value)
# Must match the sheet layout exactly:
#   Row 1  Account1 Username
#   Row 2  Account1 Password
#   Row 3  Account2 Username
#   Row 4  Account2 Password
#   Row 5  Account3 Username
#   Row 6  Account3 Password
#   Row 7  Target
#   Row 8  OTP Timeout (min)
#   Row 9  Alert Email
#   Row 10 Alert Email Password
#   Row 11 Control
# ===================================================================
CFG_ROW = {
    "account1_user":   "B1",
    "account1_pass":   "B2",
    "account2_user":   "B3",
    "account2_pass":   "B4",
    "account3_user":   "B5",
    "account3_pass":   "B6",
    "target":          "B7",
    "otp_timeout_min": "B8",
    "alert_email":     "B9",
    "alert_password":  "B10",
    "control":         "B11",
}

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
# OUTPUT / PROGRESS
# ===================================================================
OUTPUT_FILE   = "crash_reports.xlsx"
PROGRESS_FILE = "progress.txt"