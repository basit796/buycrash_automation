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
    SHEET_START, SHEET_CONFIG, NUM_ACCOUNTS, SCOPES,
    SHEET_RECHECK_FOUND, RECHECK_NUM_ACCOUNTS, OTP_TIMEOUT_MIN
)

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


def save_progress_to_sheet(next_number: int):
    """
    Write next_number into the Start Number sheet at A2.
    Called after every report (found/not-found/error) and on any
    exit path so the script always resumes from the right place.
    next_number should be last_searched + 1.
    """
    def _do():
        ws = _get_spreadsheet().worksheet(SHEET_START)
        ws.update("A2", [[str(next_number)]])
        print(f"   [PROGRESS] Saving next start number to sheet: {next_number}")
        print(f"   [SHEETS] Next start number saved: {next_number}")
    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR save_progress_to_sheet: {e}")


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


def save_created_account(email: str, email_pass: str, portal_user: str, portal_pass: str, address: str, first_name: str, last_name: str):
    def _do():
        ws = _get_or_create_worksheet("Credentials", [
            "Account Date", "Email Username", "Email Password",
            "Portal Username", "Portal Password", "Billing Address",
            "First Name", "Last Name"
        ])
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.insert_row([
            date_str, email, email_pass, portal_user, portal_pass, address, first_name, last_name
        ], 2, value_input_option="USER_ENTERED")
        print(f"   [SHEETS] Saved created account: {portal_user}")
    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR save_created_account: {e}")


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

"""
sheets_handler_recheck.py
-------------------------
Recheck-specific Google Sheets functions.
Paste these into sheets_handler.py alongside the existing functions.
 
Config sheet layout for recheck:
  B66      : daily search limit (default 200)
  B67-B70  : Account 1  (username, password, mailtm_email, mailtm_token)
  B71-B74  : Account 2
  ...
  B111-B114: Account 12
 
  B33      : control cell  (shared with normal search)
  B34      : residential proxy URL  (shared with normal search)
  B30      : alert email  (shared)
  B31      : alert email password  (shared)
 
Start Number sheet:
  B2       : recheck cursor (next report number to check)
 
Sheets:
  "Not Found"     : column A = report numbers  (row 1 = header)
  "ReCheck Found" : columns = Report Number, DOI, Date Rechecked
"""

BASE_ROW = 67   # B67 = first account username

def load_recheck_config() -> dict:
    """
    Reads recheck-specific values from the Config sheet.
    Returns a dict with keys:
      recheck_daily_limit, recheck_accounts, recheck_mailtm_tokens,
      recheck_mailtm_emails, recheck_proxy
    Designed to be merged into the main cfg dict.
    """
 
    def _do():
        ws = _get_spreadsheet().worksheet(SHEET_CONFIG)
 
        # B66 — daily limit
        try:
            val = ws.acell("B66").value
            daily_limit = int(str(val).strip()) if val and str(val).strip().isdigit() else 200
        except Exception:
            daily_limit = 200
 
        # B34 — shared proxy (same cell as normal search)
        try:
            proxy_val = ws.acell("B34").value
            recheck_proxy = str(proxy_val).strip() if proxy_val else None
        except Exception:
            recheck_proxy = None
 
        # B67-B114 — 12 accounts, 4 rows each
        # Row offsets per account: +0=username, +1=password, +2=email, +3=token
        accounts        = []
        mailtm_tokens   = []
        mailtm_emails   = []
 
        for i in range(RECHECK_NUM_ACCOUNTS):
            row_u = BASE_ROW + (i * 4)       # username
            row_p = BASE_ROW + (i * 4) + 1   # password
            row_e = BASE_ROW + (i * 4) + 2   # mailtm email
            row_t = BASE_ROW + (i * 4) + 3   # mailtm token
 
            def _cell(row):
                try:
                    v = ws.acell(f"B{row}").value
                    return str(v).strip() if v else ""
                except Exception:
                    return ""
 
            username = _cell(row_u)
            password = _cell(row_p)
            email    = _cell(row_e)
            token    = _cell(row_t)
 
            if username:
                accounts.append({"username": username, "password": password})
            mailtm_emails.append(email)
            mailtm_tokens.append(token)
 
        return {
            "recheck_daily_limit"  : daily_limit,
            "recheck_accounts"     : accounts,
            "recheck_mailtm_tokens": mailtm_tokens,
            "recheck_mailtm_emails": mailtm_emails,
            "recheck_proxy"        : recheck_proxy or None,
        }
 
    try:
        result = _with_retry(_do)
        print(f"   [SHEETS] Recheck config: {len(result['recheck_accounts'])} accounts, "
              f"limit={result['recheck_daily_limit']}, "
              f"proxy={'set' if result['recheck_proxy'] else 'none'}")
        return result
    except Exception as e:
        print(f"   [SHEETS] ERROR load_recheck_config: {e}")
        empty = [""] * RECHECK_NUM_ACCOUNTS
        return {
            "recheck_daily_limit"  : 200,
            "recheck_accounts"     : [],
            "recheck_mailtm_tokens": empty,
            "recheck_mailtm_emails": empty,
            "recheck_proxy"        : None,
        }
 
 
# -------------------------------------------------------------------
# NOT FOUND LIST — load all report numbers
# -------------------------------------------------------------------
 
def load_not_found_list() -> list:
    """
    Returns a list of report number strings from the Not Found sheet.
    Row 1 is assumed to be the header — skipped.
    Empty cells are ignored.
    """
 
    def _do():
        ws   = _get_spreadsheet().worksheet(SHEET_NOT_FOUND)
        rows = ws.col_values(1)   # column A, all rows
        # Skip header (row 1), filter empty
        numbers = [str(r).strip() for r in rows[1:] if str(r).strip()]
        return numbers
 
    try:
        numbers = _with_retry(_do)
        print(f"   [SHEETS] Not Found list loaded: {len(numbers)} entries")
        return numbers
    except Exception as e:
        print(f"   [SHEETS] ERROR load_not_found_list: {e}")
        return []
 
 
# -------------------------------------------------------------------
# REMOVE FROM NOT FOUND (deletes row, everything below shifts up)
# -------------------------------------------------------------------
 
def remove_from_not_found(report_number: str):
    """
    Find report_number in column A of Not Found sheet and delete that row.
    gspread delete_rows() shifts all rows below upward automatically.
    """
 
    def _do():
        ws   = _get_spreadsheet().worksheet(SHEET_NOT_FOUND)
        rows = ws.col_values(1)   # column A
 
        for idx, val in enumerate(rows):
            if str(val).strip() == str(report_number).strip():
                row_num = idx + 1   # gspread is 1-indexed
                ws.delete_rows(row_num)
                print(f"   [SHEETS] Removed from Not Found (row {row_num}): {report_number}")
                return True
 
        print(f"   [SHEETS] Not Found: {report_number} not found in sheet (already removed?)")
        return False
 
    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR remove_from_not_found {report_number}: {e}")
 
 
# -------------------------------------------------------------------
# RECHECK FOUND — save newly confirmed entries
# -------------------------------------------------------------------
 
def save_recheck_found(report_number: str, date_of_incident: str):
    """
    Append to the ReCheck Found sheet.
    Creates the sheet with headers if it doesn't exist yet.
    """
 
    def _do():
        ws = _get_or_create_worksheet(
            SHEET_RECHECK_FOUND,
            ["Report Number #", "DOI (Date of Incident)", "Date Rechecked"]
        )
        ws.append_row(
            [report_number, date_of_incident,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            value_input_option="USER_ENTERED"
        )
        print(f"   [SHEETS] ReCheck FOUND: {report_number} | {date_of_incident}")
 
    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR save_recheck_found: {e}")
 
 
# -------------------------------------------------------------------
# RECHECK CURSOR — read / write B2 in Start Number sheet
# -------------------------------------------------------------------
 
def get_recheck_cursor() -> str:
    """
    Read B2 in Start Number sheet.
    Returns the report number string, or None if empty/invalid.
    """ 
    def _do():
        ws  = _get_spreadsheet().worksheet(SHEET_START)
        val = ws.acell("B2").value
        if val and str(val).strip():
            return str(val).strip()
        return None
 
    try:
        cursor = _with_retry(_do)
        if cursor:
            print(f"   [SHEETS] Recheck cursor: {cursor}")
        return cursor
    except Exception as e:
        print(f"   [SHEETS] ERROR get_recheck_cursor: {e}")
        return None
 
 
def save_recheck_cursor(next_report_number):
    """
    Write next_report_number to B2 in Start Number sheet.
    """
 
    def _do():
        ws = _get_spreadsheet().worksheet(SHEET_START)
        ws.update("B2", [[str(next_report_number)]])
        print(f"   [SHEETS] Recheck cursor saved: {next_report_number}")
 
    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR save_recheck_cursor: {e}")
