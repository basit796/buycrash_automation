"""
sheets_handler.py
-----------------
All Google Sheets read/write operations with auto-reconnect on idle timeout.

Tabs:
  Found        -> Report Number # | DOI
  Not Found    -> Report Number   | Date Search
  Errors       -> Report Number # | Date Search | Error
  Start Number -> A2=start number, B2=OTP input
"""
import time
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from config import (
    SPREADSHEET_ID, CREDENTIALS_FILE,
    SHEET_FOUND, SHEET_NOT_FOUND, SHEET_ERRORS, SHEET_START,
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_MAX_RETRIES   = 3
_RETRY_BACKOFF = [5, 15, 30]

_spreadsheet = None


def _reset_connection():
    global _spreadsheet
    _spreadsheet = None


def _get_spreadsheet():
    global _spreadsheet
    if _spreadsheet is None:
        try:
            creds        = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
            client       = gspread.authorize(creds)
            _spreadsheet = client.open_by_key(SPREADSHEET_ID)
            print(f"   [SHEETS] Connected: {_spreadsheet.title}")
        except Exception as e:
            print(f"   [SHEETS] Connection failed: {e}")
            _spreadsheet = None
    return _spreadsheet


def _with_retry(fn):
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            _reset_connection()
            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF[attempt]
                print(f"   [SHEETS] Error attempt {attempt+1}/{_MAX_RETRIES}: {str(e)[:100]}")
                print(f"   [SHEETS] Reconnecting in {wait}s...")
                time.sleep(wait)
            else:
                print(f"   [SHEETS] All retries failed: {str(e)[:100]}")
    raise last_exc


def _get_or_create_worksheet(name: str, headers: list):
    sp = _get_spreadsheet()
    if sp is None:
        raise Exception("No spreadsheet connection")
    try:
        return sp.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sp.add_worksheet(title=name, rows=1000, cols=len(headers))
        ws.append_row(headers, value_input_option="USER_ENTERED")
        print(f"   [SHEETS] Created tab '{name}'")
        return ws


# -- PUBLIC API ------------------------------------------------------------

def get_start_number() -> int:
    def _do():
        ws  = _get_spreadsheet().worksheet(SHEET_START)
        val = ws.acell("A2").value
        if val and str(val).strip().isdigit():
            # number = int(str(val).strip())
            number = 1525194
            print(f"   [SHEETS] Start number: {number}")
            return number
        print(f"   [SHEETS] Start Number cell A2 empty/invalid: '{val}'")
        return 0
    try:
        return _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR get_start_number: {e}")
        return 0


def get_otp_from_sheet() -> str:
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
        print(f"   [SHEETS] ERROR get_otp: {e}")
        return None


def clear_otp_from_sheet():
    def _do():
        _get_spreadsheet().worksheet(SHEET_START).update("B2", [[""]])
    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR clear_otp: {e}")


def save_found(report_number: str, date_of_incident: str):
    def _do():
        ws = _get_or_create_worksheet(SHEET_FOUND, ["Report Number #", "DOI (Date of Incident)"])
        ws.append_row([report_number, date_of_incident], value_input_option="USER_ENTERED")
        print(f"   [SHEETS] FOUND: {report_number} | {date_of_incident}")
    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR save_found: {e}")


def save_not_found(report_number: str):
    def _do():
        ws = _get_or_create_worksheet(SHEET_NOT_FOUND, ["Report Number", "Date Search"])
        ws.append_row([report_number, datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
                      value_input_option="USER_ENTERED")
        print(f"   [SHEETS] NOT FOUND: {report_number}")
    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR save_not_found: {e}")


def save_error(report_number: str, error_message: str):
    def _do():
        ws = _get_or_create_worksheet(SHEET_ERRORS, ["Report Number #", "Date Search", "Error"])
        ws.append_row(
            [report_number, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(error_message)[:500]],
            value_input_option="USER_ENTERED"
        )
        print(f"   [SHEETS] ERROR logged: {report_number}")
    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR save_error: {e}")


def test_connection() -> bool:
    def _do():
        sp     = _get_spreadsheet()
        titles = [ws.title for ws in sp.worksheets()]
        print(f"   [SHEETS] OK. Tabs: {titles}")
        return True
    try:
        return _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] FAILED: {e}")
        return False