import os
import base64
from dotenv import load_dotenv

load_dotenv()

# --- Credentials ---
# Using SITE_USERNAME to avoid clash with Windows built-in USERNAME env var
USERNAME = os.getenv("SITE_USERNAME", "")
PASSWORD_B64 = os.getenv("PASSWORD_B64", "")

def get_password():
    return PASSWORD_B64

# --- URLs ---
BASE_URL = "https://buycrash.lexisnexisrisk.com"
LOGIN_URL = f"{BASE_URL}/login"
SEARCH_PAGE_URL = f"{BASE_URL}/ui/report/search?state=MI&jurisdiction=Detroit%20Police%20Department"
SEARCH_API_URL = f"{BASE_URL}/search-svc/ssrqop/search"

# --- Search Settings ---
STATE = "MI"
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
OUTPUT_FILE = "crash_reports.xlsx"
PROGRESS_FILE = "progress.txt"  # stores last checked report number