"""
sheets_handler.py
-----------------
All Google Sheets operations with auto-reconnect on idle-timeout.

Config tab layout (column A = label, column B = value):
  B1  Account1 Username
  B2  Account1 Password
  B3  Account2 Username
  B4  Account2 Password
  B5  Account3 Username
  B6  Account3 Password
  B7  Target
  B8  OTP Timeout (min)
  B9  Alert Email
  B10 Alert Email Password
  B11 Control  (pause / stop / restart — cleared after reading)
"""
import time
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

from config import (
    SPREADSHEET_ID, CREDENTIALS_FILE, CFG_ROW,
    SHEET_FOUND, SHEET_NOT_FOUND, SHEET_ERRORS,
    SHEET_START, SHEET_CONFIG,
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_MAX_RETRIES   = 3
_RETRY_BACKOFF = [5, 15, 30]
_spreadsheet   = None


# -------------------------------------------------------------------
# Connection
# -------------------------------------------------------------------

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


# -------------------------------------------------------------------
# CONFIG TAB — read all settings at once
# -------------------------------------------------------------------

def load_config() -> dict:
    """
    Read all values from the Config tab and return a dict.
    Called once at startup and again on restart.
    Falls back to empty strings for missing values.
    """
    def _do():
        ws     = _get_spreadsheet().worksheet(SHEET_CONFIG)
        result = {}
        for key, cell in CFG_ROW.items():
            try:
                val = ws.acell(cell).value
                result[key] = str(val).strip() if val else ""
            except Exception:
                result[key] = ""
        return result

    try:
        cfg = _with_retry(_do)
        # Parse accounts list
        accounts = []
        for i in range(1, 4):
            u = cfg.get(f"account{i}_user", "").strip()
            p = cfg.get(f"account{i}_pass", "").strip()
            if u:
                accounts.append({"username": u, "password": p})
        cfg["accounts"] = accounts
        cfg["target"]   = int(cfg.get("target", "100") or "100")
        cfg["otp_timeout_min"] = int(cfg.get("otp_timeout_min", "60") or "60")

        # Build proxy list — skip empty rows
        proxies = []
        for i in range(1, 8):
            p = cfg.get(f"proxy_{i}", "").strip()
            if p:
                proxies.append(p)
        cfg["proxies"] = proxies

        print(f"   [SHEETS] Config loaded: {len(accounts)} accounts, "
              f"target={cfg['target']}, otp={cfg['otp_timeout_min']}min, "
              f"proxies={len(proxies)}")
        return cfg
    except Exception as e:
        print(f"   [SHEETS] ERROR loading config: {e}")
        return {"accounts": [], "target": 100, "otp_timeout_min": 60,
                "alert_email": "", "alert_password": "", "control": "",
                "proxies": []}


# -------------------------------------------------------------------
# CONTROL CELL — checked after every search
# -------------------------------------------------------------------

def check_control() -> str:
    """
    Read B11 (Control cell) from Config tab.
    Returns lowercase value if it's pause/stop/restart, else "".
    Clears the cell after reading a recognised command.
    """
    def _do():
        ws  = _get_spreadsheet().worksheet(SHEET_CONFIG)
        val = ws.acell(CFG_ROW["control"]).value
        if not val:
            return ""
        cmd = str(val).strip().lower()
        if cmd in ("pause", "stop", "restart"):
            ws.update(CFG_ROW["control"], [[""]])   # clear immediately
            print(f"   [CONTROL] Command received: {cmd.upper()}")
            return cmd
        return ""

    try:
        return _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR reading control cell: {e}")
        return ""


# -------------------------------------------------------------------
# START NUMBER / OTP
# -------------------------------------------------------------------

def get_start_number() -> int:
    def _do():
        ws  = _get_spreadsheet().worksheet(SHEET_START)
        val = ws.acell("A2").value
        if val and str(val).strip().isdigit():
            return int(str(val).strip())
        return 0
    try:
        num = _with_retry(_do)
        if num:
            print(f"   [SHEETS] Start number: {num}")
        return num
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


# -------------------------------------------------------------------
# WRITE RESULTS
# -------------------------------------------------------------------

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