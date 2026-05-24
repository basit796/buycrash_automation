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
TOTAL_SLOTS               = 10     # 9 accounts + 1 no-login
NO_LOGIN_SLOT             = 9      # index of the no-login slot
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
# NEW LAYOUT — 9 accounts:
#
#   --- ACCOUNTS (B1 - B18, 2 rows each) ---
#   B1   Account1 Username    (site login)
#   B2   Account1 Password
#   B3   Account2 Username
#   B4   Account2 Password
#   B5   Account3 Username
#   B6   Account3 Password
#   B7   Account4 Username
#   B8   Account4 Password
#   B9   Account5 Username
#   B10  Account5 Password
#   B11  Account6 Username
#   B12  Account6 Password
#   B13  Account7 Username
#   B14  Account7 Password
#   B15  Account8 Username
#   B16  Account8 Password
#   B17  Account9 Username
#   B18  Account9 Password
#
#   --- SETTINGS (B19 - B26) ---
#   B19  Target               (number of reports to find)
#   B20  Alert Email
#   B21  Alert Email Password
#   B22  (empty)
#   B23  Control              (pause / stop / restart — cleared after reading)
#   B24  Residential Proxy    (optional — http://ip:port or socks5://ip:port)
#                              Leave EMPTY for direct connection (fallback)
#   B25  (empty)
#   B26  (empty)
#
#   --- MAIL.TM TOKENS (B27 - B44, 2 rows each) ---
#   B27  Account1 Mail.tm Email
#   B28  Account1 Mail.tm Token
#   B29  Account2 Mail.tm Email
#   B30  Account2 Mail.tm Token
#   B31  Account3 Mail.tm Email
#   B32  Account3 Mail.tm Token
#   B33  Account4 Mail.tm Email
#   B34  Account4 Mail.tm Token
#   B35  Account5 Mail.tm Email
#   B36  Account5 Mail.tm Token
#   B37  Account6 Mail.tm Email
#   B38  Account6 Mail.tm Token
#   B39  Account7 Mail.tm Email
#   B40  Account7 Mail.tm Token
#   B41  Account8 Mail.tm Email
#   B42  Account8 Mail.tm Token
#   B43  Account9 Mail.tm Email
#   B44  Account9 Mail.tm Token
#
# Proxy URL formats accepted:
#   http://ip:port                    (plain HTTP proxy)
#   http://user:pass@ip:port          (authenticated HTTP proxy)
#   socks5://user:pass@ip:port        (SOCKS5 — needs pip install requests[socks])
# ===================================================================
CFG_ROW = {
    # Accounts
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
    # Settings
    "target":           "B19",
    "alert_email":      "B20",
    "alert_password":   "B21",
    # B22 empty
    "control":          "B23",
    "residential_proxy":"B24",
    # B25, B26 empty
    # Mail.tm tokens
    "mailtm_email_1":   "B27",
    "mailtm_token_1":   "B28",
    "mailtm_email_2":   "B29",
    "mailtm_token_2":   "B30",
    "mailtm_email_3":   "B31",
    "mailtm_token_3":   "B32",
    "mailtm_email_4":   "B33",
    "mailtm_token_4":   "B34",
    "mailtm_email_5":   "B35",
    "mailtm_token_5":   "B36",
    "mailtm_email_6":   "B37",
    "mailtm_token_6":   "B38",
    "mailtm_email_7":   "B39",
    "mailtm_token_7":   "B40",
    "mailtm_email_8":   "B41",
    "mailtm_token_8":   "B42",
    "mailtm_email_9":   "B43",
    "mailtm_token_9":   "B44",
}

# Number of accounts supported
NUM_ACCOUNTS = 9

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