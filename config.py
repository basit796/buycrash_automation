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
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

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
TOTAL_SLOTS               = 15     # 14 accounts + 1 no-login
NO_LOGIN_SLOT             = 14     # index of the no-login slot
BATCH_SIZE                = 15     # reports per slot per cycle
INTER_BATCH_PAUSE_SEC     = 60     # 1 min between slots
LIMIT_PAUSE_SEC           = 60     # 1 min pause when a slot hits SEARCH_LIMIT
ALL_SLOTS_LIMIT_PAUSE_SEC = 600    # 10 min when ALL slots hit limit
RESTART_PAUSE_SEC         = 60     # 1 min pause on "restart" control command
CONSECUTIVE_ERROR_LIMIT   = 20     # stop after N back-to-back errors
MAX_PROXY_ROTATIONS       = 0      # disabled — single residential IP, no rotation

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
# CONFIG SHEET ROW MAPPING  (column B = value)
#
# NEW LAYOUT — 14 accounts:
#
#   --- ACCOUNTS (B1 - B28, 2 rows each) ---
#   B1   Account1 Username
#   B2   Account1 Password
#   B3   Account2 Username
#   B4   Account2 Password
#   ...
#   B27  Account14 Username
#   B28  Account14 Password
#
#   --- SETTINGS (B29 - B36) ---
#   B29  Target
#   B30  Alert Email
#   B31  Alert Email Password
#   B32  (empty)
#   B33  Control
#   B34  Residential Proxy
#   B35  (empty)
#   B36  (empty)
#
#   --- MAIL.TM TOKENS (B37 - B64, 2 rows each) ---
#   B37  Account1 Mail.tm Email
#   B38  Account1 Mail.tm Token
#   B39  Account2 Mail.tm Email
#   B40  Account2 Mail.tm Token
#   ...
#   B63  Account14 Mail.tm Email
#   B64  Account14 Mail.tm Token
#
# ===================================================================
CFG_ROW = {
    # Accounts (14 accounts × 2 rows = B1-B28)
    "account1_user":    "B1",
    "account1_pass":    "B2",
    "account2_user":    "B3",
    "account2_pass":    "B4",
    "account3_user":    "B5",
    "account3_pass":    "B6",
    "account4_user":    "B7",
    "account4_pass":    "B8",
    "account5_user":    "B9",
    "account5_pass":    "B10",
    "account6_user":    "B11",
    "account6_pass":    "B12",
    "account7_user":    "B13",
    "account7_pass":    "B14",
    "account8_user":    "B15",
    "account8_pass":    "B16",
    "account9_user":    "B17",
    "account9_pass":    "B18",
    "account10_user":   "B19",
    "account10_pass":   "B20",
    "account11_user":   "B21",
    "account11_pass":   "B22",
    "account12_user":   "B23",
    "account12_pass":   "B24",
    "account13_user":   "B25",
    "account13_pass":   "B26",
    "account14_user":   "B27",
    "account14_pass":   "B28",
    # Settings
    "target":           "B29",
    "alert_email":      "B30",
    "alert_password":   "B31",
    # B32 empty
    "control":          "B33",
    "residential_proxy":"B34",
    # B35, B36 empty
    # Mail.tm tokens (14 accounts × 2 rows = B37-B64)
    "mailtm_email_1":   "B37",
    "mailtm_token_1":   "B38",
    "mailtm_email_2":   "B39",
    "mailtm_token_2":   "B40",
    "mailtm_email_3":   "B41",
    "mailtm_token_3":   "B42",
    "mailtm_email_4":   "B43",
    "mailtm_token_4":   "B44",
    "mailtm_email_5":   "B45",
    "mailtm_token_5":   "B46",
    "mailtm_email_6":   "B47",
    "mailtm_token_6":   "B48",
    "mailtm_email_7":   "B49",
    "mailtm_token_7":   "B50",
    "mailtm_email_8":   "B51",
    "mailtm_token_8":   "B52",
    "mailtm_email_9":   "B53",
    "mailtm_token_9":   "B54",
    "mailtm_email_10":  "B55",
    "mailtm_token_10":  "B56",
    "mailtm_email_11":  "B57",
    "mailtm_token_11":  "B58",
    "mailtm_email_12":  "B59",
    "mailtm_token_12":  "B60",
    "mailtm_email_13":  "B61",
    "mailtm_token_13":  "B62",
    "mailtm_email_14":  "B63",
    "mailtm_token_14":  "B64",
}

# Number of accounts supported
NUM_ACCOUNTS = 14

# OTP timeout is hardcoded
OTP_TIMEOUT_MIN = 60

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

# Recheck accounts — 12 accounts, 4 rows each starting at B67
RECHECK_NUM_ACCOUNTS = 12
RECHECK_BATCH_SIZE   = 15      # same as normal BATCH_SIZE
 
# Sheet names
SHEET_RECHECK_FOUND  = "ReCheck Found"   # new sheet for recheck hits
# SHEET_NOT_FOUND, SHEET_START, SHEET_CONFIG already defined above
 
# Config sheet cell references for recheck
# (These are already in CFG_ROW format for convenience)
RECHECK_CFG = {
    "daily_limit": "B66",
    "proxy":       "B34",   # shared with normal search
    "control":     "B33",   # shared with normal search
    "alert_email": "B30",   # shared with normal search
    "alert_pass":  "B31",   # shared with normal search
}
 
# Account block starts at row 67, 4 rows per account:
#   B(67 + i*4 + 0) = username
#   B(67 + i*4 + 1) = password
#   B(67 + i*4 + 2) = mailtm email
#   B(67 + i*4 + 3) = mailtm token
# Last account (12th) ends at B114.
RECHECK_ACCOUNT_BASE_ROW = 67
# ==================================================