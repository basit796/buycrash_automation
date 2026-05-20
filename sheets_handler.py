"""
sheets_handler.py
-----------------
Handles all Google Sheets read/write operations.

Sheets in the spreadsheet (client-facing, minimal fields):
  - "Found"        -> Report Number # | DOI (Date of Incident)
  - "Not Found"    -> Report Number   | Date Search
  - "Errors"       -> Report Number # | Date Search | Error
  - "Start Number" -> Starting report number in A2, OTP in B2
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# -- Config ---------------------------------------------------------------
SPREADSHEET_ID   = "1kn5uju5c2yh4PHHFAQDm-SRK3vDhCeEjLfdgDkFPZP8"
CREDENTIALS_FILE = "google_credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Sheet tab names (must match exactly what's in your spreadsheet)
SHEET_FOUND     = "Found"
SHEET_NOT_FOUND = "Not Found"
SHEET_ERRORS    = "Errors"
SHEET_START     = "Start Number"

# -- Internal connection cache --------------------------------------------
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


def _get_or_create_worksheet(name: str, headers: list):
    """
    Return the worksheet with the given name.
    If it doesn't exist, create it and write the header row.
    """
    sp = _get_spreadsheet()
    try:
        return sp.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sp.add_worksheet(title=name, rows=1000, cols=len(headers))
        ws.append_row(headers, value_input_option="USER_ENTERED")
        print(f"   [SHEETS] Created new tab '{name}' with headers")
        return ws


# -- PUBLIC FUNCTIONS ------------------------------------------------------

def get_start_number() -> int:
    """
    Read the starting report number from the 'Start Number' sheet, cell A2.
    Returns an int. Falls back to 0 if the cell is empty or missing.
    """
    try:
        ws  = _get_spreadsheet().worksheet(SHEET_START)
        val = ws.acell("A2").value
        if val and str(val).strip().isdigit():
            number = int(str(val).strip())
            print(f"   [SHEETS] Start number from Google Sheet: {number}")
            return number
        else:
            print(f"   [SHEETS] WARNING: Start Number cell A2 empty or invalid: '{val}'")
            return 0
    except gspread.exceptions.WorksheetNotFound:
        print(f"   [SHEETS] ERROR: Tab '{SHEET_START}' not found")
        return 0
    except Exception as e:
        print(f"   [SHEETS] ERROR reading start number: {e}")
        return 0


def get_otp_from_sheet() -> str:
    """
    Read the OTP code from the 'Start Number' sheet, cell B2.
    Returns the OTP string if it looks like a 4-8 digit code, else None.
    """
    try:
        ws  = _get_spreadsheet().worksheet(SHEET_START)
        val = ws.acell("B2").value
        if val:
            code = str(val).strip().replace(" ", "")
            if code.isdigit() and 4 <= len(code) <= 8:
                return code
        return None
    except Exception as e:
        print(f"   [SHEETS] ERROR reading OTP from B2: {e}")
        return None


def clear_otp_from_sheet():
    """Clear cell B2 in 'Start Number' sheet after OTP is used."""
    try:
        ws = _get_spreadsheet().worksheet(SHEET_START)
        ws.update("B2", [[""]])
    except Exception as e:
        print(f"   [SHEETS] ERROR clearing OTP from B2: {e}")


def save_found(report_number: str, date_of_incident: str):
    """
    Append a row to the 'Found' sheet (client fields only):
      Report Number # | DOI (Date of Incident)
    """
    try:
        ws = _get_or_create_worksheet(
            SHEET_FOUND,
            ["Report Number #", "DOI (Date of Incident)"]
        )
        row = [report_number, date_of_incident]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"   [SHEETS] FOUND saved: {report_number} | {date_of_incident}")
    except Exception as e:
        print(f"   [SHEETS] ERROR saving FOUND: {e}")


def save_not_found(report_number: str):
    """
    Append a row to the 'Not Found' sheet (client fields only):
      Report Number | Date Search
    """
    try:
        ws = _get_or_create_worksheet(
            SHEET_NOT_FOUND,
            ["Report Number", "Date Search"]
        )
        date_search = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [report_number, date_search]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"   [SHEETS] NOT FOUND saved: {report_number}")
    except Exception as e:
        print(f"   [SHEETS] ERROR saving NOT FOUND: {e}")


def save_error(report_number: str, error_message: str):
    """
    Append a row to the 'Errors' sheet (client fields only):
      Report Number # | Date Search | Error
    """
    try:
        ws = _get_or_create_worksheet(
            SHEET_ERRORS,
            ["Report Number #", "Date Search", "Error"]
        )
        date_search = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [report_number, date_search, str(error_message)[:500]]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"   [SHEETS] ERROR saved: {report_number} | {error_message[:80]}")
    except Exception as e:
        print(f"   [SHEETS] ERROR saving to Errors sheet: {e}")


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
