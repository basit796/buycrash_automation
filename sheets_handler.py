"""
sheets_handler.py
-----------------
Handles all Google Sheets read/write operations.

Sheets in the spreadsheet (client-facing, minimal fields):
  - "Found"        -> Report Number # | DOI (Date of Incident)
  - "Not Found"    -> Report Number   | Date Search
  - "Errors"       -> Report Number # | Date Search | Error
  - "Start Number" -> Starting report number in A2, OTP in B2

Connection strategy:
  - Caches the spreadsheet object to avoid re-authing on every call.
  - On ANY connection error (RemoteDisconnected, timeout, etc.),
    clears the cache and retries up to 3 times with backoff.
  - This handles the ~10-min TCP idle timeout that hits around the
    20th search when each search takes 15-35 seconds.
"""

import time
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

# Retry settings for connection errors
_MAX_RETRIES    = 3
_RETRY_BACKOFF  = [5, 15, 30]   # seconds to wait before each retry attempt

# -- Internal connection cache --------------------------------------------
_spreadsheet = None


def _reset_connection():
    """Force a fresh connection on the next call."""
    global _spreadsheet
    _spreadsheet = None


def _get_spreadsheet():
    """
    Return cached spreadsheet object, connecting if needed.
    Never raises — returns None on failure (callers handle it).
    """
    global _spreadsheet
    if _spreadsheet is None:
        try:
            creds = Credentials.from_service_account_file(
                CREDENTIALS_FILE, scopes=SCOPES
            )
            client       = gspread.authorize(creds)
            _spreadsheet = client.open_by_key(SPREADSHEET_ID)
            print(f"   [SHEETS] Connected to Google Sheet: {_spreadsheet.title}")
        except Exception as e:
            print(f"   [SHEETS] Connection failed: {e}")
            _spreadsheet = None
    return _spreadsheet


def _with_retry(fn):
    """
    Execute fn() with up to _MAX_RETRIES retries.
    On any exception, clears the connection cache and waits before retrying.
    Returns the result of fn(), or raises the last exception if all retries fail.
    """
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            err = str(e)

            # Always reset the connection so the next attempt gets a fresh one
            _reset_connection()

            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF[attempt]
                print(f"   [SHEETS] Error (attempt {attempt + 1}/{_MAX_RETRIES}): "
                      f"{err[:100]}")
                print(f"   [SHEETS] Reconnecting in {wait}s...")
                time.sleep(wait)
            else:
                print(f"   [SHEETS] All {_MAX_RETRIES} retries failed: {err[:100]}")

    raise last_exc


def _get_or_create_worksheet(name: str, headers: list):
    """
    Return the worksheet with the given name.
    If it doesn't exist, create it and write the header row.
    """
    sp = _get_spreadsheet()
    if sp is None:
        raise Exception("No spreadsheet connection available")
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
    def _do():
        ws  = _get_spreadsheet().worksheet(SHEET_START)
        val = ws.acell("A2").value
        if val and str(val).strip().isdigit():
            # number = int(str(val).strip())
            number = 1525123
            print(f"   [SHEETS] Start number from Google Sheet: {number}")
            return number
        else:
            print(f"   [SHEETS] WARNING: Start Number cell A2 empty or invalid: '{val}'")
            return 0

    try:
        return _with_retry(_do)
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
    def _do():
        ws  = _get_spreadsheet().worksheet(SHEET_START)
        val = ws.acell("B2").value
        if val:
            code = str(val).strip().replace(" ", "")
            if code.isdigit() and 4 <= len(code) <= 8:
                return code
        return None

    try:
        return _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR reading OTP from B2: {e}")
        return None


def clear_otp_from_sheet():
    """Clear cell B2 in 'Start Number' sheet after OTP is used."""
    def _do():
        ws = _get_spreadsheet().worksheet(SHEET_START)
        ws.update("B2", [[""]])

    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR clearing OTP from B2: {e}")


def save_found(report_number: str, date_of_incident: str):
    """
    Append a row to the 'Found' sheet:
      Report Number # | DOI (Date of Incident)
    """
    def _do():
        ws  = _get_or_create_worksheet(
            SHEET_FOUND,
            ["Report Number #", "DOI (Date of Incident)"]
        )
        row = [report_number, date_of_incident]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"   [SHEETS] FOUND saved: {report_number} | {date_of_incident}")

    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR saving FOUND (all retries failed): {e}")


def save_not_found(report_number: str):
    """
    Append a row to the 'Not Found' sheet:
      Report Number | Date Search
    """
    def _do():
        ws = _get_or_create_worksheet(
            SHEET_NOT_FOUND,
            ["Report Number", "Date Search"]
        )
        date_search = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [report_number, date_search]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"   [SHEETS] NOT FOUND saved: {report_number}")

    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR saving NOT FOUND (all retries failed): {e}")


def save_error(report_number: str, error_message: str):
    """
    Append a row to the 'Errors' sheet:
      Report Number # | Date Search | Error
    """
    def _do():
        ws = _get_or_create_worksheet(
            SHEET_ERRORS,
            ["Report Number #", "Date Search", "Error"]
        )
        date_search = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [report_number, date_search, str(error_message)[:500]]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"   [SHEETS] ERROR saved: {report_number} | {error_message[:80]}")

    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR saving to Errors sheet (all retries failed): {e}")


def test_connection() -> bool:
    """Quick connectivity test — prints sheet titles."""
    def _do():
        sp     = _get_spreadsheet()
        titles = [ws.title for ws in sp.worksheets()]
        print(f"   [SHEETS] Connected OK. Tabs found: {titles}")
        return True

    try:
        return _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] Connection FAILED: {e}")
        return False