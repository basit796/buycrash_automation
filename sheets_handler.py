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

Recheck layout (column B):
  B66      Daily recheck search limit (default 200)
  B67-B70  Recheck Account 1  (username, password, mailtm_email, mailtm_token)
  B71-B74  Recheck Account 2
  ...
  B111-B114 Recheck Account 12

Start Number sheet:
  A2       Normal search cursor (next report number)
  B2       Recheck cursor (next report number to recheck)
"""

import time
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

from config import (
    SPREADSHEET_ID, CREDENTIALS_FILE, CFG_ROW,
    SHEET_FOUND, SHEET_NOT_FOUND, SHEET_ERRORS,
    SHEET_START, SHEET_CONFIG, NUM_ACCOUNTS, SCOPES,
    SHEET_RECHECK_FOUND, RECHECK_NUM_ACCOUNTS, OTP_TIMEOUT_MIN,
    RECHECK_ACCOUNT_BASE_ROW,
)

_MAX_RETRIES   = 3
_RETRY_BACKOFF = [5, 15, 30]
_spreadsheet   = None


# ===================================================================
# CONNECTION
# ===================================================================

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


# ===================================================================
# CONFIG TAB — read all settings at once
# ===================================================================

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

        # ── Residential proxy (B24) ───────────────────────────────────
        residential_proxy        = cfg.get("residential_proxy", "").strip()
        cfg["residential_proxy"] = residential_proxy or None
        cfg["proxies"]           = [residential_proxy] if residential_proxy else []

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

        # Map site username -> mailtm token for fast lookup
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
        return {
            "accounts": [], "target": 100, "otp_timeout_min": OTP_TIMEOUT_MIN,
            "alert_email": "", "alert_password": "", "control": "",
            "residential_proxy": None, "proxies": [],
            "mailtm_tokens": empty_tokens,
            "mailtm_emails": empty_tokens,
            "mailtm_by_username": {},
        }


# ===================================================================
# CONTROL CELL — checked after every search
# ===================================================================

def check_control() -> str:
    """
    Read control cell from Config tab.
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
            ws.update(CFG_ROW["control"], [[""]])
            print(f"   [CONTROL] Command received: {cmd.upper()}")
            return cmd
        return ""

    try:
        return _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR reading control cell: {e}")
        return ""


# ===================================================================
# START NUMBER / OTP
# ===================================================================

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
    Called after every report and on any exit path.
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


# ===================================================================
# WRITE RESULTS
# ===================================================================

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
        ws.append_row(
            [report_number, datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            value_input_option="USER_ENTERED"
        )
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


def save_created_account(
    email: str, email_pass: str, portal_user: str,
    portal_pass: str, address: str, first_name: str, last_name: str
):
    def _do():
        ws = _get_or_create_worksheet("Credentials", [
            "Account Date", "Email Username", "Email Password",
            "Portal Username", "Portal Password", "Billing Address",
            "First Name", "Last Name"
        ])
        ws.insert_row(
            [datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             email, email_pass, portal_user, portal_pass, address, first_name, last_name],
            2, value_input_option="USER_ENTERED"
        )
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


# ===================================================================
# RECHECK FUNCTIONS
# ===================================================================

def load_recheck_config() -> dict:
    """
    Reads recheck accounts and settings from Config sheet.

    Layout:
      B66       = daily search limit
      B67       = account1 username
      B68       = account1 password
      B69       = account1 mailtm email
      B70       = account1 mailtm token
      B71-B74   = account2 (same pattern)
      ...
      B111-B114 = account12

    Returns dict with keys:
      recheck_daily_limit, recheck_accounts,
      recheck_mailtm_tokens, recheck_mailtm_emails, recheck_proxy
    """
    def _do():
        ws = _get_spreadsheet().worksheet(SHEET_CONFIG)

        # Read ALL column B values in one API call — avoids closure bug
        # and is much faster than individual acell() calls in a loop
        last_row  = RECHECK_ACCOUNT_BASE_ROW + (RECHECK_NUM_ACCOUNTS * 4) - 1
        all_b     = ws.col_values(2)   # column B, 0-indexed list

        def _cell(row):
            """Get value at 1-indexed row N of column B. Returns '' if missing."""
            idx = row - 1
            if idx < len(all_b):
                v = all_b[idx]
                return str(v).strip() if v else ""
            return ""

        # B66 — daily limit
        try:
            raw         = _cell(66)
            daily_limit = int(raw) if raw.isdigit() else 200
        except Exception:
            daily_limit = 200

        # B34 — proxy (shared with normal search)
        proxy_val     = _cell(34)
        recheck_proxy = proxy_val if proxy_val else None

        # B67-B114 — 12 accounts, 4 rows each
        accounts      = []
        mailtm_tokens = []
        mailtm_emails = []

        for i in range(RECHECK_NUM_ACCOUNTS):
            base     = RECHECK_ACCOUNT_BASE_ROW + (i * 4)
            username = _cell(base)
            password = _cell(base + 1)
            email    = _cell(base + 2)
            token    = _cell(base + 3)

            if username:
                accounts.append({"username": username, "password": password})
            mailtm_emails.append(email)
            mailtm_tokens.append(token)

        return {
            "recheck_daily_limit"  : daily_limit,
            "recheck_accounts"     : accounts,
            "recheck_mailtm_tokens": mailtm_tokens,
            "recheck_mailtm_emails": mailtm_emails,
            "recheck_proxy"        : recheck_proxy,
        }

    try:
        result = _with_retry(_do)
        print(f"   [SHEETS] Recheck config loaded: "
              f"{len(result['recheck_accounts'])} accounts, "
              f"limit={result['recheck_daily_limit']}, "
              f"proxy={'set' if result['recheck_proxy'] else 'none'}, "
              f"mailtm={sum(1 for t in result['recheck_mailtm_tokens'] if t)} tokens")
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


def load_not_found_list() -> list:
    """
    Returns list of report number strings from the Not Found sheet.
    Skips row 1 (header). Ignores empty cells.
    Only reads column A (report numbers).
    """
    def _do():
        ws   = _get_spreadsheet().worksheet(SHEET_NOT_FOUND)
        rows = ws.col_values(1)   # column A
        return [str(r).strip() for r in rows[1:] if str(r).strip()]

    try:
        numbers = _with_retry(_do)
        print(f"   [SHEETS] Not Found list: {len(numbers)} entries")
        return numbers
    except Exception as e:
        print(f"   [SHEETS] ERROR load_not_found_list: {e}")
        return []


def remove_from_not_found(report_number: str):
    """
    Find report_number in column A of Not Found sheet and delete that row.
    gspread delete_rows() shifts everything below upward automatically.
    Skips row 1 (header) — will never delete it.
    """
    def _do():
        ws   = _get_spreadsheet().worksheet(SHEET_NOT_FOUND)
        rows = ws.col_values(1)   # column A, all rows

        for idx, val in enumerate(rows):
            if str(val).strip() == str(report_number).strip():
                row_num = idx + 1   # gspread is 1-indexed
                if row_num == 1:
                    print(f"   [SHEETS] Skipping row 1 (header) for {report_number}")
                    return False
                ws.delete_rows(row_num)
                print(f"   [SHEETS] Removed from Not Found (row {row_num}): {report_number}")
                return True

        print(f"   [SHEETS] {report_number} not found in Not Found sheet (already removed?)")
        return False

    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR remove_from_not_found {report_number}: {e}")


def save_recheck_found(report_number: str, date_of_incident: str):
    """Append to ReCheck Found sheet. Creates it with headers if needed."""
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


def get_recheck_cursor() -> str:
    """Read B2 from Start Number sheet. Returns report number string or None."""
    def _do():
        ws  = _get_spreadsheet().worksheet(SHEET_START)
        val = ws.acell("B2").value
        return str(val).strip() if val and str(val).strip() else None

    try:
        cursor = _with_retry(_do)
        if cursor:
            print(f"   [SHEETS] Recheck cursor: {cursor}")
        return cursor
    except Exception as e:
        print(f"   [SHEETS] ERROR get_recheck_cursor: {e}")
        return None


def save_recheck_cursor(next_report_number):
    """Write next_report_number to B2 in Start Number sheet."""
    def _do():
        ws = _get_spreadsheet().worksheet(SHEET_START)
        ws.update("B2", [[str(next_report_number)]])
        print(f"   [SHEETS] Recheck cursor saved: {next_report_number}")

    try:
        _with_retry(_do)
    except Exception as e:
        print(f"   [SHEETS] ERROR save_recheck_cursor: {e}")