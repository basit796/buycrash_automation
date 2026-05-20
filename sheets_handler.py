"""
sheets_handler.py
-----------------
Handles all Google Sheets read/write operations.

Sheets in the spreadsheet:
  - "Found"        → Report Number | DOI (Date of Incident)
  - "Not Found"    → Report Number | Date Searched
  - "Start Number" → Starting report number in cell A2
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────
SPREADSHEET_ID   = "1kn5uju5c2yh4PHHFAQDm-SRK3vDhCeEjLfdgDkFPZP8"
CREDENTIALS_FILE = "google_credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Sheet tab names (must match exactly what's in your spreadsheet)
SHEET_FOUND       = "Found"
SHEET_NOT_FOUND   = "Not Found"
SHEET_START       = "Start Number"

# ── Internal connection cache ───────────────────────────────────────────
_spreadsheet = None


def _get_spreadsheet():
    """Return cached spreadsheet object, connecting if needed."""
    global _spreadsheet
    if _spreadsheet is None:
        creds = Credentials.from_service_account_file(
            CREDENTIALS_FILE, scopes=SCOPES
        )
        client = gspread.authorize(creds)
        _spreadsheet = client.open_by_key(SPREADSHEET_ID)
        print(f"   [SHEETS] Connected to Google Sheet: {_spreadsheet.title}")
    return _spreadsheet


# ── PUBLIC FUNCTIONS ────────────────────────────────────────────────────

def get_start_number() -> int:
    """
    Read the starting report number from the 'Start Number' sheet, cell A2.
    Returns an int. Falls back to 0 if the cell is empty or missing.
    """
    try:
        ws = _get_spreadsheet().worksheet(SHEET_START)
        val = ws.acell("A2").value
        if val and str(val).strip().isdigit():
            number = int(str(val).strip())
            print(f"   [SHEETS] Start number from Google Sheet: {number}")
            return number
        else:
            print(f"   [SHEETS] WARNING: Start Number sheet cell A2 is empty or invalid: '{val}'")
            return 0
    except gspread.exceptions.WorksheetNotFound:
        print(f"   [SHEETS] ERROR: Sheet tab '{SHEET_START}' not found in spreadsheet")
        return 0
    except Exception as e:
        print(f"   [SHEETS] ERROR reading start number: {e}")
        return 0


def save_found(report_number: str, date_of_incident: str):
    """
    Append a row to the 'Found' sheet:
      [Report Number, DOI]
    """
    try:
        ws  = _get_spreadsheet().worksheet(SHEET_FOUND)
        row = [report_number, date_of_incident]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"   [SHEETS] FOUND saved: {report_number} | {date_of_incident}")
    except gspread.exceptions.WorksheetNotFound:
        print(f"   [SHEETS] ERROR: Tab '{SHEET_FOUND}' not found — row not saved")
    except Exception as e:
        print(f"   [SHEETS] ERROR saving FOUND: {e}")


def save_not_found(report_number: str):
    """
    Append a row to the 'Not Found' sheet:
      [Report Number, Date Searched]
    """
    try:
        ws           = _get_spreadsheet().worksheet(SHEET_NOT_FOUND)
        date_searched = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row          = [report_number, date_searched]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"   [SHEETS] NOT FOUND saved: {report_number}")
    except gspread.exceptions.WorksheetNotFound:
        print(f"   [SHEETS] ERROR: Tab '{SHEET_NOT_FOUND}' not found — row not saved")
    except Exception as e:
        print(f"   [SHEETS] ERROR saving NOT FOUND: {e}")


def test_connection() -> bool:
    """Quick connectivity test — prints sheet titles."""
    try:
        sp     = _get_spreadsheet()
        titles = [ws.title for ws in sp.worksheets()]
        print(f"   [SHEETS] Connected OK. Tabs found: {titles}")
        return True
    except Exception as e:
        print(f"   [SHEETS] Connection FAILED: {e}")
        return False
