"""
recheck_runner.py
-----------------
Orchestrates the daily Not Found recheck process.

Called either:
  - Automatically after normal search completes (from main.py)
  - Manually via POST /recheck/start  (from api.py)

Flow:
  1. Load recheck accounts from Config sheet (B67-B114, 12 accounts)
  2. Load daily limit from B66
  3. Load cursor from Start Number sheet B2
  4. Load Not Found list (all report numbers)
  5. Find cursor position in list, or start from beginning if past end
  6. Iterate in RECHECK_BATCH_SIZE chunks, rotating through 12 accounts
  7. On found:   write to ReCheck Found sheet, delete from Not Found sheet
  8. On not-found: update cursor, continue
  9. Stop when daily_limit searches done, or list exhausted
 10. Save cursor to B2 for tomorrow
 11. Send success/error email
"""

import time
from datetime import datetime

import sheets_handler
import mailer
from config import (
    RECHECK_BATCH_SIZE,
    RECHECK_NUM_ACCOUNTS,
    INTER_BATCH_PAUSE_SEC,
    LIMIT_PAUSE_SEC,
    ALL_SLOTS_LIMIT_PAUSE_SEC,
    CONSECUTIVE_ERROR_LIMIT,
)
from recheck_searcher import get_recheck_session, run_recheck_slot_batch


# ─────────────────────────────────────────────────
# Runtime state — module-level so api.py can read them
# ─────────────────────────────────────────────────
_searches_done = 0
_found_count   = 0
_error_count   = 0
_start_time    = time.time()
_abort         = False


def request_abort():
    global _abort
    _abort = True


def _elapsed():
    return time.time() - _start_time


def _slot_label(slot_idx: int, accounts: list) -> str:
    if slot_idx < len(accounts):
        return f"Slot {slot_idx} / Account {slot_idx+1}: {accounts[slot_idx]['username']}"
    return f"Slot {slot_idx} (no account)"


def _countdown(label: str, seconds: int, interval: int = 30):
    for remaining in range(seconds, 0, -interval):
        if _abort:
            return
        m, s = divmod(remaining, 60)
        print(f"   [{label}] Resuming in {m}m {s:02d}s...  ", end="\r")
        time.sleep(min(interval, remaining))
    print()


# ─────────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────────

def _make_callbacks(counters: dict):
    """
    counters = {"searches": 0, "found": 0, "errors": 0}
    All three callbacks increment counters["searches"] so the daily_limit
    check in run_recheck_slot_batch is always the exact live count.
    """
    def on_found(record: dict):
        counters["searches"] += 1
        counters["found"]    += 1
        rn  = str(record.get("reportNumber", ""))
        doi = str(record.get("dateOfIncident", ""))
        sheets_handler.save_recheck_found(rn, doi)
        sheets_handler.remove_from_not_found(rn)
        print(f"   [RECHECK] FOUND & removed from Not Found: {rn}")

    def on_not_found(report_number: str):
        counters["searches"] += 1
        print(f"   [RECHECK] Still not found: {report_number}")

    def on_error(report_number: str, error_msg: str):
        counters["searches"] += 1
        counters["errors"]   += 1
        sheets_handler.save_error(f"RECHECK:{report_number}", error_msg)
        print(f"   [RECHECK ERROR] {report_number}: {error_msg[:80]}")

    return on_found, on_not_found, on_error


# ─────────────────────────────────────────────────
# PROXY SWITCHING
# ─────────────────────────────────────────────────

def _handle_all_slots_limit(cfg: dict, counters: dict, active_proxy: str) -> str:
    configured_proxy = cfg.get("recheck_proxy")
    wait_min         = ALL_SLOTS_LIMIT_PAUSE_SEC // 60
    alert_email      = cfg.get("alert_email", "")
    alert_password   = cfg.get("alert_password", "")

    if not active_proxy and configured_proxy:
        host = configured_proxy.split('@')[-1] if '@' in configured_proxy else configured_proxy
        print(f"\n{'!'*60}")
        print(f"  RECHECK: ALL SLOTS HIT LIMIT on direct IP")
        print(f"  Switching to residential proxy: {host}")
        print(f"{'!'*60}")
        mailer.send_proxies_exhausted(
            cfg, counters["found"], counters["searches"], _elapsed(), 0, 0)
        return configured_proxy

    elif active_proxy and configured_proxy:
        print(f"\n{'!'*60}")
        print(f"  RECHECK: PROXY ALSO HIT LIMIT — back to direct, waiting {wait_min} min")
        print(f"{'!'*60}")
        mailer.send_proxies_exhausted(
            cfg, counters["found"], counters["searches"], _elapsed(), 0, wait_min)
        _countdown("RECHECK ALL-SLOTS LIMIT", ALL_SLOTS_LIMIT_PAUSE_SEC)
        return None

    else:
        print(f"\n{'!'*60}")
        print(f"  RECHECK: ALL SLOTS HIT LIMIT — no proxy, waiting {wait_min} min")
        print(f"{'!'*60}")
        mailer.send_proxies_exhausted(
            cfg, counters["found"], counters["searches"], _elapsed(), 0, wait_min)
        _countdown("RECHECK ALL-SLOTS LIMIT", ALL_SLOTS_LIMIT_PAUSE_SEC)
        return None


# ─────────────────────────────────────────────────
# CURSOR SAVE HELPER
# ─────────────────────────────────────────────────

def _save_recheck_cursor(not_found_numbers: list, cursor_pos: int):
    """Write the report number at cursor_pos to Start Number sheet B2."""
    if not_found_numbers and cursor_pos < len(not_found_numbers):
        next_report = not_found_numbers[cursor_pos]
    elif not_found_numbers:
        next_report = not_found_numbers[0]   # wrap to beginning
    else:
        next_report = 0
    sheets_handler.save_recheck_cursor(next_report)


# ─────────────────────────────────────────────────
# MAIN RECHECK RUN
# ─────────────────────────────────────────────────

def run_recheck(cfg: dict = None) -> str:
    """
    Entry point. cfg should already have recheck keys merged in
    (recheck_accounts, recheck_daily_limit, recheck_mailtm_tokens, recheck_proxy).
    If cfg is None, loads fresh from sheets.

    Returns: "done" | "stop" | "restart" | "consecutive_errors" | "crash"
    """
    global _searches_done, _found_count, _error_count, _start_time, _abort

    # Reset everything before each run
    _start_time    = time.time()
    _abort         = False
    _searches_done = 0
    _found_count   = 0
    _error_count   = 0

    counters = {"searches": 0, "found": 0, "errors": 0}

    # ── Load config ───────────────────────────────────────────────
    if cfg is None:
        cfg = sheets_handler.load_config()
        cfg.update(sheets_handler.load_recheck_config())

    accounts        = cfg.get("recheck_accounts", [])
    daily_limit     = cfg.get("recheck_daily_limit", 200)
    otp_timeout_min = cfg.get("otp_timeout_min", 5)
    mailtm_tokens   = cfg.get("recheck_mailtm_tokens", [])
    active_proxy    = None

    if not accounts:
        print("[RECHECK] No recheck accounts configured — skipping")
        return "done"

    print("\n" + "=" * 60)
    print("  RECHECK RUN STARTING")
    print(f"  Date        : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Accounts    : {len(accounts)}")
    print(f"  Daily limit : {daily_limit}")
    print(f"  OTP method  : {'Mail.tm (auto)' if any(mailtm_tokens) else 'Sheet B2 (manual)'}")
    print(f"  Proxy       : {'configured' if cfg.get('recheck_proxy') else 'none (direct)'}")
    print("=" * 60)

    # ── Load Not Found list ───────────────────────────────────────
    not_found_numbers = sheets_handler.load_not_found_list()
    if not not_found_numbers:
        print("[RECHECK] Not Found list is empty — nothing to recheck")
        mailer.send_recheck_success(cfg, 0, 0, 0, _elapsed(), "Not Found list is empty")
        return "done"

    print(f"[RECHECK] Not Found list: {len(not_found_numbers)} entries")

    # ── Find cursor position ──────────────────────────────────────
    cursor_report = sheets_handler.get_recheck_cursor()

    if not cursor_report:
        cursor_pos = 0
        print("[RECHECK] No cursor in sheet — starting from beginning of Not Found list")

    elif cursor_report in not_found_numbers:
        cursor_pos = not_found_numbers.index(cursor_report)
        print(f"[RECHECK] Resuming from report #{cursor_report} (position {cursor_pos})")

    else:
        # Cursor report was removed (found in a previous run) —
        # find the first entry numerically >= cursor
        try:
            cursor_int = int(cursor_report)
            next_pos   = next(
                (i for i, r in enumerate(not_found_numbers) if int(r) >= cursor_int),
                None
            )
            if next_pos is not None:
                cursor_pos = next_pos
                print(f"[RECHECK] Cursor #{cursor_report} removed — "
                      f"advancing to #{not_found_numbers[cursor_pos]} (pos {cursor_pos})")
            else:
                cursor_pos = 0
                print(f"[RECHECK] Cursor #{cursor_report} past end — wrapping to beginning")
        except (ValueError, TypeError):
            cursor_pos = 0
            print(f"[RECHECK] Cursor '{cursor_report}' unreadable — starting from beginning")

    on_found, on_not_found, on_error = _make_callbacks(counters)

    # ── Main loop ─────────────────────────────────────────────────
    slot_idx               = 0
    cycle_num              = 0
    ALL_LOGIN_FAIL_LIMIT   = 3 * len(accounts)   # e.g. 36 for 12 accounts
    consecutive_login_fail = 0
    limit_count_this_round = 0   # track all-slots-limit per round

    while counters["searches"] < daily_limit:

        if _abort:
            _save_recheck_cursor(not_found_numbers, cursor_pos)
            print("[RECHECK] Aborted via stop command")
            return "stop"

        # Build next batch
        batch = []
        pos   = cursor_pos
        while len(batch) < RECHECK_BATCH_SIZE and pos < len(not_found_numbers):
            batch.append(not_found_numbers[pos])
            pos += 1

        if not batch:
            print("[RECHECK] Reached end of Not Found list — wrapping to beginning")
            cursor_pos        = 0
            not_found_numbers = sheets_handler.load_not_found_list()
            if not not_found_numbers:
                print("[RECHECK] Not Found list now empty — done")
                break
            continue

        cycle_num += 1
        acct_idx   = slot_idx % len(accounts)

        print(f"\n{'#'*60}")
        print(f"  RECHECK CYCLE #{cycle_num:03d}")
        print(f"  Account    : {_slot_label(acct_idx, accounts)}")
        print(f"  Batch      : {batch[0]} → {batch[-1]}")
        print(f"  Progress   : {counters['searches']}/{daily_limit} searches today")
        print(f"  IP mode    : {'proxy' if active_proxy else 'direct'}")
        print(f"{'#'*60}")

        # Inter-slot pause (skip first cycle)
        if cycle_num > 1:
            print(f"\n   [INTER-SLOT] {INTER_BATCH_PAUSE_SEC//60} min pause...")
            _countdown("INTER-SLOT", INTER_BATCH_PAUSE_SEC)

        # ── Acquire session ───────────────────────────────────────
        try:
            api_session = get_recheck_session(
                slot_idx        = acct_idx,
                accounts        = accounts,
                otp_timeout_min = otp_timeout_min,
                proxy           = active_proxy,
                mailtm_tokens   = mailtm_tokens,
            )
        except Exception as e:
            err = str(e)
            print(f"\n   [RECHECK LOGIN FAIL] {_slot_label(acct_idx, accounts)}: {err[:100]}")
            sheets_handler.save_error(f"RECHECK_LOGIN_SLOT{acct_idx}", err[:300])
            consecutive_login_fail += 1
            if consecutive_login_fail >= ALL_LOGIN_FAIL_LIMIT:
                print("[RECHECK] Too many consecutive login failures — pausing 10 min")
                mailer.send_crash(
                    cfg,
                    Exception("Recheck: all accounts failed login repeatedly"),
                    counters["found"], counters["searches"], _elapsed()
                )
                _countdown("RECHECK ALL-LOGIN-FAIL", 600)
                consecutive_login_fail = 0
            else:
                print("   Skipping to next account...")
            slot_idx += 1
            continue

        consecutive_login_fail = 0

        # ── Run the batch ─────────────────────────────────────────
        processed, last_report, status = run_recheck_slot_batch(
            slot_idx           = acct_idx,
            api_session        = api_session,
            report_numbers     = batch,
            found_callback     = on_found,
            not_found_callback = on_not_found,
            error_callback     = on_error,
            counters           = counters,
            daily_limit        = daily_limit,
        )

        # Re-load list (on_found may have deleted rows) then advance cursor
        not_found_numbers = sheets_handler.load_not_found_list()
        if last_report and last_report in not_found_numbers:
            cursor_pos = not_found_numbers.index(last_report) + 1
        else:
            cursor_pos += processed

        _save_recheck_cursor(not_found_numbers, cursor_pos)

        print(f"\n   [{_slot_label(acct_idx, accounts)}] Done. "
              f"Status={status} | Processed={processed} | "
              f"Found={counters['found']} | Searches={counters['searches']}/{daily_limit}")

        # ── Handle status ─────────────────────────────────────────
        if status == "daily_limit":
            break

        elif status == "ok":
            limit_count_this_round = 0
            slot_idx += 1

        elif status == "limit":
            limit_count_this_round += 1
            print(f"\n   [RECHECK LIMIT] Slot {acct_idx} — pausing {LIMIT_PAUSE_SEC//60} min")
            _countdown("RECHECK LIMIT", LIMIT_PAUSE_SEC)
            slot_idx += 1
            # If every account in one full round hit limit → proxy switch
            if limit_count_this_round >= len(accounts):
                active_proxy           = _handle_all_slots_limit(cfg, counters, active_proxy)
                limit_count_this_round = 0

        elif status == "session":
            print("   Session expired — re-logging next cycle")
            slot_idx += 1

        elif status == "consecutive_errors":
            _save_recheck_cursor(not_found_numbers, cursor_pos)
            mailer.send_consecutive_errors(
                cfg, str(last_report), "Recheck: 20 consecutive errors",
                counters["found"], counters["searches"], _elapsed()
            )
            return "consecutive_errors"

        elif status == "control:stop":
            _save_recheck_cursor(not_found_numbers, cursor_pos)
            mailer.send_user_stop(cfg, counters["found"], counters["searches"], _elapsed())
            return "stop"

        elif status == "control:restart":
            _save_recheck_cursor(not_found_numbers, cursor_pos)
            mailer.send_restart(cfg, counters["found"], counters["searches"], _elapsed(), 0)
            return "restart"

        slot_idx = slot_idx % len(accounts)

    # ── Done ──────────────────────────────────────────────────────
    _save_recheck_cursor(not_found_numbers, cursor_pos)

    # Sync back to module-level so api.py /recheck/status can read them
    _searches_done = counters["searches"]
    _found_count   = counters["found"]
    _error_count   = counters["errors"]

    print(f"\n[RECHECK] Complete — "
          f"Searched={counters['searches']} | "
          f"Found={counters['found']} | "
          f"Errors={counters['errors']}")

    mailer.send_recheck_success(
        cfg,
        counters["found"],
        counters["searches"],
        counters["errors"],
        _elapsed()
    )
    return "done"