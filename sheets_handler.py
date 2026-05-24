"""
sheets_handler.py
-----------------
All Google Sheets operations with auto-reconnect on idle-timeout.

Config tab layout (column A = label, column B = value):
  B1-B18   Account 1-9 credentials (Username / Password pairs)
  B19      Target
  B20      Alert Email
  B21      Alert Email Password
  B23      Control  (pause / stop / restart — cleared after reading)
  B24      Residential Proxy URL  (optional, leave empty = direct connection)
  B27-B44  Account 1-9 Mail.tm Email + Token pairs
"""
import time
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

from config import (
    SPREADSHEET_ID, CREDENTIALS_FILE, CFG_ROW,
    SHEET_FOUND, SHEET_NOT_FOUND, SHEET_ERRORS,
    SHEET_START, SHEET_CONFIG, NUM_ACCOUNTS,
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

        # ── Accounts (up to NUM_ACCOUNTS) ─────────────────────────────
        accounts = []
        for i in range(1, NUM_ACCOUNTS + 1):
            u = cfg.get(f"account{i}_user", "").strip()
            p = cfg.get(f"account{i}_pass", "").strip()
            if u:
                accounts.append({"username": u, "password": p})
        cfg["accounts"] = accounts
        cfg["target"]   = int(cfg.get("target", "100") or "100")

        # ── OTP timeout (hardcoded) ───────────────────────────────────
        from config import OTP_TIMEOUT_MIN
        cfg["otp_timeout_min"] = OTP_TIMEOUT_MIN

        # ── Residential proxy (B24) — single static IP ────────────────
        # Accepts: http://ip:port  |  http://user:pass@ip:port
        #          socks5://user:pass@ip:port  |  empty = direct
        residential_proxy = cfg.get("residential_proxy", "").strip()
        cfg["residential_proxy"] = residential_proxy or None
        # Keep cfg["proxies"] as single-element list for backward compat
        cfg["proxies"] = [residential_proxy] if residential_proxy else []

        # ── Mail.tm tokens (B27-B44) ──────────────────────────────────
        mailtm_tokens = []
        mailtm_emails = []
        for i in range(1, NUM_ACCOUNTS + 1):
            email = cfg.get(f"mailtm_email_{i}", "").strip()
            token = cfg.get(f"mailtm_token_{i}", "").strip()
            mailtm_emails.append(email)
            mailtm_tokens.append(token)
        cfg["mailtm_emails"] = mailtm_emails
        cfg["mailtm_tokens"] = mailtm_tokens

        # Map site username -> mailtm token for fast lookup in searcher
        cfg["mailtm_by_username"] = {}
        for i, acc in enumerate(accounts):
            if i < len(mailtm_tokens) and mailtm_tokens[i]:
                cfg["mailtm_by_username"][acc["username"]] = mailtm_tokens[i]

        print(f"   [SHEETS] Config loaded: {len(accounts)} accounts, "
              f"target={cfg['target']}, "
              f"proxy={'set (' + residential_proxy.split('@')[-1] + ')' if residential_proxy else 'none (direct)'}, "
              f"mailtm={sum(1 for t in mailtm_tokens if t)} tokens")
        return cfg
    except Exception as e:
        print(f"   [SHEETS] ERROR loading config: {e}")
        from config import OTP_TIMEOUT_MIN
        empty_tokens = [""] * NUM_ACCOUNTS
        return {"accounts": [], "target": 100, "otp_timeout_min": OTP_TIMEOUT_MIN,
                "alert_email": "", "alert_password": "", "control": "",
                "residential_proxy": None, "proxies": [],
                "mailtm_tokens": empty_tokens,
                "mailtm_emails": empty_tokens,
                "mailtm_by_username": {}}


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