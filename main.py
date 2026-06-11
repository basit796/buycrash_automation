"""
main.py
-------
Orchestrator for BuyCrash report automation.

Usage:
    python main.py                  # normal run
    python main.py --reset          # reset progress, start fresh
    python main.py --start 1525123  # override start report number

Auto-terminates after 12 hours as a safety net.
"""
import argparse
import sys
import time
import traceback
from datetime import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import sheets_handler
import mailer
from config import (
    TOTAL_SLOTS, NO_LOGIN_SLOT, BATCH_SIZE,
    INTER_BATCH_PAUSE_SEC, LIMIT_PAUSE_SEC,
    ALL_SLOTS_LIMIT_PAUSE_SEC, RESTART_PAUSE_SEC,
    CONSECUTIVE_ERROR_LIMIT,
)
from progress import load_progress, save_progress, reset_progress
from excel_handler import save_found_report, save_not_found_report, get_summary
from searcher import get_session_for_slot, run_slot_batch
import recheck_runner

# ===================================================================
# AUTO-TERMINATE AFTER 12 HOURS
# ===================================================================
MAX_RUN_HOURS   = 12
MAX_RUN_SECONDS = MAX_RUN_HOURS * 3600
_script_start   = time.time()


def _check_timeout():
    """Call this periodically — returns True if 12h limit exceeded."""
    elapsed = time.time() - _script_start
    if elapsed >= MAX_RUN_SECONDS:
        print(f"\n{'!'*60}")
        print(f"  AUTO-TERMINATE: {MAX_RUN_HOURS}h time limit reached")
        print(f"  Started : {datetime.fromtimestamp(_script_start).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Now     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'!'*60}")
        return True
    return False


def _time_remaining_str() -> str:
    elapsed  = time.time() - _script_start
    left_sec = max(0, MAX_RUN_SECONDS - elapsed)
    h, r     = divmod(int(left_sec), 3600)
    m, s     = divmod(r, 60)
    return f"{h}h {m}m {s}s"


# -------------------------------------------------------------------
# Runtime counters
# -------------------------------------------------------------------
_found_total     = 0
_searches_done   = 0
_not_found_count = 0
_error_count     = 0
_start_time      = time.time()


def _elapsed() -> float:
    return time.time() - _start_time


# -------------------------------------------------------------------
# Slot label
# -------------------------------------------------------------------

def _slot_label(slot_idx: int, accounts: list) -> str:
    if slot_idx == NO_LOGIN_SLOT:
        return f"Slot {NO_LOGIN_SLOT} / NO-LOGIN"
    if slot_idx < len(accounts):
        return f"Slot {slot_idx} / Account {slot_idx+1}: {accounts[slot_idx]['username']}"
    return f"Slot {slot_idx} (no account)"


# -------------------------------------------------------------------
# Progress helpers — save to both local file AND Google Sheet
# -------------------------------------------------------------------

def _save_progress_everywhere(next_number: int):
    """
    Persist next_number in both the local progress file and A2 of the
    Start Number sheet.  next_number = last_searched_report + 1.
    """
    save_progress(next_number)
    sheets_handler.save_progress_to_sheet(next_number)


# -------------------------------------------------------------------
# Callbacks
# -------------------------------------------------------------------

def _make_callbacks(cfg: dict):
    global _found_total, _searches_done, _not_found_count, _error_count

    def on_found(record: dict):
        global _found_total, _searches_done
        _found_total   += 1
        _searches_done += 1
        # save_found_report(record)
        rn = str(record.get("reportNumber", ""))
        sheets_handler.save_found(
            report_number    = rn,
            date_of_incident = str(record.get("dateOfIncident", "")),
        )
        # Persist progress: next search = this report + 1
        try:
            _save_progress_everywhere(int(rn) + 1)
        except Exception:
            pass

    def on_not_found(report_number: str):
        global _searches_done, _not_found_count
        _searches_done   += 1
        _not_found_count += 1
        # save_not_found_report(report_number)
        sheets_handler.save_not_found(report_number)
        # Persist progress: next search = this report + 1
        try:
            _save_progress_everywhere(int(report_number) + 1)
        except Exception:
            pass

    def on_error(report_number: str, error_msg: str):
        global _searches_done, _error_count
        _searches_done += 1
        _error_count   += 1
        print(f"   [ERROR FINAL] {report_number}: {error_msg[:80]}")
        sheets_handler.save_error(report_number, error_msg)
        # save_not_found_report(f"ERROR:{report_number}")
        # Persist progress even on error: next search = this report + 1
        try:
            _save_progress_everywhere(int(report_number) + 1)
        except Exception:
            pass

    return on_found, on_not_found, on_error


# -------------------------------------------------------------------
# Pause helpers
# -------------------------------------------------------------------

def _countdown(label: str, seconds: int, interval: int = 30):
    for remaining in range(seconds, 0, -interval):
        # Check timeout during long waits
        if _check_timeout():
            return
        m, s = divmod(remaining, 60)
        print(f"   [{label}] Resuming in {m}m {s:02d}s...  ", end="\r")
        time.sleep(min(interval, remaining))
    print()


def _inter_slot_pause(from_idx: int, to_idx: int, accounts: list):
    print(f"\n   [INTER-SLOT] {INTER_BATCH_PAUSE_SEC//60} min  "
          f"({_slot_label(from_idx, accounts)} -> {_slot_label(to_idx, accounts)})")
    _countdown("INTER-SLOT", INTER_BATCH_PAUSE_SEC)


def _limit_pause(slot_idx: int, report_num: int, accounts: list):
    print(f"\n   [LIMIT PAUSE] {LIMIT_PAUSE_SEC//60} min after limit on "
          f"{_slot_label(slot_idx, accounts)} — next slot resumes from {report_num}")
    _countdown("LIMIT", LIMIT_PAUSE_SEC)


# -------------------------------------------------------------------
# ALL SLOTS LIMIT — proxy switching logic
# -------------------------------------------------------------------

def _handle_all_slots_limit(cfg: dict, cursor: int, active_proxy: str) -> str:
    configured_proxy = cfg.get("residential_proxy")
    wait_min         = ALL_SLOTS_LIMIT_PAUSE_SEC // 60

    if not active_proxy and configured_proxy:
        host = configured_proxy.split('@')[-1] if '@' in configured_proxy else configured_proxy
        print(f"\n{'!'*60}")
        print(f"  ALL SLOTS HIT LIMIT on direct IP")
        print(f"  Switching to residential proxy: {host}")
        print(f"  Resuming immediately from #{cursor}")
        print(f"{'!'*60}")
        mailer.send_proxies_exhausted(cfg, _found_total, _searches_done,
                                      _elapsed(), cursor, 0)
        return configured_proxy

    elif active_proxy and configured_proxy:
        print(f"\n{'!'*60}")
        print(f"  PROXY ALSO HIT LIMIT — switching back to direct IP")
        print(f"  Waiting {wait_min} min before retrying from #{cursor}")
        print(f"{'!'*60}")
        mailer.send_proxies_exhausted(cfg, _found_total, _searches_done,
                                      _elapsed(), cursor, wait_min)
        _countdown("ALL-SLOTS LIMIT", ALL_SLOTS_LIMIT_PAUSE_SEC)
        return None

    else:
        print(f"\n{'!'*60}")
        print(f"  ALL SLOTS HIT LIMIT — no proxy configured")
        print(f"  Waiting {wait_min} min before retrying from #{cursor}")
        print(f"{'!'*60}")
        mailer.send_proxies_exhausted(cfg, _found_total, _searches_done,
                                      _elapsed(), cursor, wait_min)
        _countdown("ALL-SLOTS LIMIT", ALL_SLOTS_LIMIT_PAUSE_SEC)
        return None


# -------------------------------------------------------------------
# SINGLE RUN
# -------------------------------------------------------------------

def _run(cfg: dict, start_report: int) -> str:
    global _found_total, _searches_done, _not_found_count, _error_count, _start_time

    accounts        = cfg["accounts"]
    target          = cfg["target"]
    otp_timeout_min = cfg["otp_timeout_min"]

    on_found, on_not_found, on_error = _make_callbacks(cfg)

    current_report = start_report
    cycle_num      = 0
    active_proxy   = None

    # How many back-to-back cycles had ZERO successful logins.
    # If this hits ALL_LOGIN_FAIL_CYCLE_LIMIT we pause and alert rather
    # than spinning forever on the same report numbers.
    ALL_LOGIN_FAIL_CYCLE_LIMIT = 3
    consecutive_all_login_fail = 0

    print(f"\nTarget  : {target} valid reports")
    print(f"Starting: report #{current_report}")
    print(f"Accounts: {len(accounts)}")
    print(f"Proxy   : {'configured (will use if needed)' if cfg.get('residential_proxy') else 'none (direct only)'}")
    print(f"Alert   : {cfg.get('alert_email') or 'not configured'}")
    print(f"Timeout : auto-terminate in {_time_remaining_str()}\n")

    while _found_total < target:

        if _check_timeout():
            _save_progress_everywhere(current_report)
            mailer.send_crash(cfg,
                              Exception(f"Auto-terminated after {MAX_RUN_HOURS}h"),
                              _found_total, _searches_done, _elapsed())
            return "timeout"

        cycle_num        += 1
        cursor            = current_report
        limit_count       = 0
        login_fail_count  = 0   # slots that failed login this cycle

        print(f"\n{'#'*60}")
        print(f"  CYCLE #{cycle_num:03d}  —  cursor={cursor}  found={_found_total}/{target}")
        print(f"  Active IP : {'proxy' if active_proxy else 'direct'}")
        print(f"  Time left : {_time_remaining_str()}")
        print(f"{'#'*60}")

        last_active_slot = None
        slots_attempted  = 0

        for slot_idx in range(TOTAL_SLOTS):

            if _check_timeout():
                _save_progress_everywhere(cursor)
                mailer.send_crash(cfg,
                                  Exception(f"Auto-terminated after {MAX_RUN_HOURS}h"),
                                  _found_total, _searches_done, _elapsed())
                return "timeout"

            if _found_total >= target:
                break

            batch = list(range(cursor, cursor + BATCH_SIZE))

            print(f"\n{'='*60}")
            print(f"  {_slot_label(slot_idx, accounts)}")
            print(f"  Reports : {batch[0]} -> {batch[-1]}  |  Found: {_found_total}/{target}")
            print(f"  IP mode : {'proxy' if active_proxy else 'direct'}")
            print(f"{'='*60}")

            if last_active_slot is not None:
                _inter_slot_pause(last_active_slot, slot_idx, accounts)

            # Acquire session
            try:
                api_session = get_session_for_slot(
                    slot_idx, accounts, otp_timeout_min,
                    active_proxy, cfg.get("mailtm_tokens", [])
                )
            except Exception as e:
                err = str(e)
                if "OTP_TIMEOUT" in err:
                    lbl      = _slot_label(slot_idx, accounts)
                    acc      = accounts[slot_idx] if slot_idx < len(accounts) else {}
                    username = acc.get("username", "")
                    password = acc.get("password", "")
                    print(f"\n   [OTP TIMEOUT] {lbl} — skipping, resuming from {cursor}")
                    mailer.send_otp_required(cfg, slot_idx, lbl, username, password)
                    sheets_handler.save_error(f"OTP_TIMEOUT_SLOT{slot_idx}",
                                              f"OTP timeout for {lbl}")
                elif "LOGIN_FAILED" in err:
                    print(f"\n   [LOGIN FAILED] {_slot_label(slot_idx, accounts)} — skipping")
                elif "LOGIN_TIMEOUT" in err:
                    print(f"\n   [LOGIN TIMEOUT] {_slot_label(slot_idx, accounts)} — browser hung, skipping")
                    sheets_handler.save_error(f"LOGIN_TIMEOUT_SLOT{slot_idx}",
                                              f"Browser login timed out for {_slot_label(slot_idx, accounts)}")
                else:
                    print(f"\n   [SESSION ERROR] {_slot_label(slot_idx, accounts)}: {e}")
                login_fail_count += 1
                last_active_slot  = slot_idx
                continue

            slots_attempted += 1
            found_in_slot, next_report, status = run_slot_batch(
                slot_idx           = slot_idx,
                api_session        = api_session,
                report_numbers     = batch,
                found_callback     = on_found,
                not_found_callback = on_not_found,
                error_callback     = on_error,
                found_so_far       = _found_total,
                target             = target,
            )

            last_active_slot = slot_idx

            print(f"\n   [{_slot_label(slot_idx, accounts)}] Done. "
                  f"Status={status} | Next={next_report} | "
                  f"Total found={_found_total}/{target}")

            if status == "ok":
                cursor = next_report

            elif status == "limit":
                limit_count += 1
                cursor       = next_report
                _limit_pause(slot_idx, cursor, accounts)

            elif status == "session":
                cursor = next_report
                print(f"   Session lost — next slot resumes from {cursor}")

            elif status == "consecutive_errors":
                _save_progress_everywhere(next_report)
                mailer.send_consecutive_errors(
                    cfg, str(next_report), "20 consecutive errors",
                    _found_total, _searches_done, _elapsed()
                )
                return "consecutive_errors"

            elif status == "control:stop":
                _save_progress_everywhere(next_report)
                mailer.send_user_stop(cfg, _found_total, _searches_done, _elapsed())
                return "stop"

            elif status == "control:restart":
                _save_progress_everywhere(next_report)
                mailer.send_restart(cfg, _found_total, _searches_done,
                                    _elapsed(), next_report)
                return "restart"

            # Save after every slot regardless of status
            _save_progress_everywhere(cursor)

            if _found_total >= target:
                break

        # ── End of cycle ─────────────────────────────────────────────
        if _found_total >= target:
            break

        # All slots failed login — cursor hasn't moved at all
        if slots_attempted == 0 and login_fail_count == TOTAL_SLOTS:
            consecutive_all_login_fail += 1
            print(f"\n{'!'*60}")
            print(f"  ALL {TOTAL_SLOTS} SLOTS FAILED LOGIN this cycle "
                  f"({consecutive_all_login_fail}/{ALL_LOGIN_FAIL_CYCLE_LIMIT})")
            print(f"  cursor stays at #{cursor} — no numbers were skipped")
            print(f"{'!'*60}")
            if consecutive_all_login_fail >= ALL_LOGIN_FAIL_CYCLE_LIMIT:
                print(f"  {ALL_LOGIN_FAIL_CYCLE_LIMIT} consecutive all-login-fail cycles — pausing 10 min then alerting")
                _save_progress_everywhere(cursor)
                mailer.send_crash(
                    cfg,
                    Exception(f"All slots failed login for {ALL_LOGIN_FAIL_CYCLE_LIMIT} cycles in a row"),
                    _found_total, _searches_done, _elapsed()
                )
                _countdown("ALL-LOGIN-FAIL", 600)   # wait 10 min, then retry
                consecutive_all_login_fail = 0       # reset and keep going
            else:
                print(f"  Waiting 2 min before retrying...")
                _countdown("ALL-LOGIN-FAIL", 120)
            # cursor does NOT move — same numbers will be retried next cycle
            current_report = cursor
        elif slots_attempted > 0 and limit_count >= slots_attempted:
            consecutive_all_login_fail = 0
            active_proxy = _handle_all_slots_limit(cfg, cursor, active_proxy)
        else:
            consecutive_all_login_fail = 0
            current_report = cursor

        _save_progress_everywhere(current_report)
        print(f"\nCycle #{cycle_num:03d} complete. Next from #{current_report}. "
              f"Found {_found_total}/{target} | IP: {'proxy' if active_proxy else 'direct'}")

    return "done"


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------

def main():
    global _found_total, _searches_done, _not_found_count, _error_count, _start_time

    parser = argparse.ArgumentParser(description="BuyCrash Report Automation")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--start", type=int)
    args = parser.parse_args()

    print("=" * 60)
    print("  BuyCrash Report Automation")
    print(f"  Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Timeout : auto-terminate after {MAX_RUN_HOURS}h")
    print("=" * 60)

    while True:
        _found_total      = 0
        _searches_done    = 0
        _not_found_count  = 0
        _error_count      = 0
        _start_time       = time.time()

        if _check_timeout():
            print(f"\n[EXIT] {MAX_RUN_HOURS}h limit reached before cycle could start.")
            break

        print("\nChecking Google Sheets connection...")
        if not sheets_handler.test_connection():
            print("Cannot connect to Google Sheets — check credentials. Exiting.")
            return

        print("\nLoading config from Config sheet...")
        cfg = sheets_handler.load_config()
        if not cfg["accounts"]:
            print("No accounts found in Config sheet. Exiting.")
            return

        if args.reset:
            reset_progress()

        if args.start:
            start_report = args.start
            print(f"Start override from CLI: {start_report}")
        else:
            gs_start = sheets_handler.get_start_number()
            if gs_start and gs_start > 0:
                start_report = gs_start
                print(f"Start from Google Sheet: {start_report}")
            else:
                start_report = load_progress()
                print(f"Start from progress file: {start_report}")

        print(f"\n  Accounts       : {len(cfg['accounts'])}")
        print(f"  Target         : {cfg['target']}")
        print(f"  OTP timeout    : {cfg['otp_timeout_min']} min")
        print(f"  Alert email    : {cfg.get('alert_email') or 'not set'}")
        print(f"  Batch size     : {BATCH_SIZE} / slot")
        print(f"  Consec. limit  : {CONSECUTIVE_ERROR_LIMIT} errors")
        print(f"  Proxy          : {'configured' if cfg.get('residential_proxy') else 'none'}")
        print(f"  Time remaining : {_time_remaining_str()}")
        print()

        outcome = "crash"
        try:
            outcome = _run(cfg, start_report)
        except Exception as e:
            print(f"\n[CRASH] Unhandled exception: {e}")
            print(traceback.format_exc())
            # Save whatever cursor we had before the crash
            try:
                _save_progress_everywhere(start_report)
            except Exception:
                pass
            mailer.send_crash(cfg, e, _found_total, _searches_done, _elapsed())
            outcome = "crash"

        if outcome == "done":
            print("\n" + "=" * 60)
            print(f"  SUCCESS — {_found_total}/{cfg['target']} reports found")
            print(f"  Time    : {mailer._fmt_elapsed(_elapsed())}")
            print(f"  Searches: {_searches_done}")
            print("=" * 60)
            mailer.send_success(
                cfg, _found_total, cfg["target"],
                _searches_done, _elapsed(),
                _not_found_count, _error_count
            )
            # get_summary()
 
            # ── Auto-trigger recheck after normal search ──────────
            print("\n" + "=" * 60)
            print("  NORMAL SEARCH DONE — starting Not Found recheck...")
            print("=" * 60)
            try:
                # Pass cfg=None so run_recheck loads its own recheck config
                # from the sheet (B66-B114). The normal-search cfg does not
                # contain recheck_accounts / recheck_proxy / recheck_daily_limit,
                # which would cause the "No recheck accounts configured" skip.
                print("   [RECHECK] Loading recheck config from sheet...")
                recheck_cfg = sheets_handler.load_recheck_config()
                recheck_outcome = recheck_runner.run_recheck(recheck_cfg)
                print(f"\n[RECHECK] Finished with outcome: {recheck_outcome}")
            except Exception as e:
                print(f"\n[RECHECK] Crashed: {e}")
                print(traceback.format_exc())
 
            break

        elif outcome == "restart":
            print(f"\n[RESTART] Pausing {RESTART_PAUSE_SEC // 60} min then restarting...")
            time.sleep(RESTART_PAUSE_SEC)
            args.start = None
            print("[RESTART] Reloading config and starting over...\n")
            continue

        elif outcome == "timeout":
            print(f"\n[EXIT] Auto-terminated after {MAX_RUN_HOURS}h")
            # get_summary()
            break

        elif outcome in ("stop", "consecutive_errors", "crash"):
            print(f"\n[EXIT] Reason: {outcome}")
            # get_summary()
            break


if __name__ == "__main__":
    main()