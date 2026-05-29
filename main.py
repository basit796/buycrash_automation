"""
main.py
-------
Orchestrator for BuyCrash report automation.

Usage:
    python main.py                  # normal run
    python main.py --reset          # ignored (progress.txt removed), kept for compat
    python main.py --start 1525123  # override start report number

Flow each run:
  Phase 1 — Re-check up to NOT_FOUND_RECHECK_LIMIT entries from the
             Not Found sheet.  Any that come back as Found are moved
             to the Found sheet and removed from Not Found.
  Phase 2 — Sequential fresh search starting from the number stored
             in the Start Number sheet (A2), continuing until the
             daily target is reached.

On every exit the next cursor is written back to A2 so the next run
resumes exactly where this one stopped.  A2 is cleared the moment it
is read at startup to prevent stale reuse.

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
from excel_handler import save_found_report, save_not_found_report, get_summary
from searcher import get_session_for_slot, run_slot_batch

# ===================================================================
# HOW MANY NOT-FOUND ENTRIES TO RE-CHECK EACH RUN
# Keep this low enough that Phase 2 still has budget for fresh numbers.
# With ~300 total searches/day, 100 re-checks leaves 200 for fresh work.
# ===================================================================
NOT_FOUND_RECHECK_LIMIT = 100

# ===================================================================
# AUTO-TERMINATE AFTER 12 HOURS
# ===================================================================
MAX_RUN_HOURS   = 12
MAX_RUN_SECONDS = MAX_RUN_HOURS * 3600
_script_start   = time.time()


def _check_timeout():
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
# Phase 1 (Not Found re-checks)
_recheck_searched  = 0   # how many not-found entries were re-checked
_recheck_found     = 0   # how many of those came back as Found

# Phase 2 (fresh sequential)
_fresh_found       = 0
_fresh_searches    = 0

# Shared / legacy (kept so mailer calls still work)
_found_total       = 0
_searches_done     = 0
_not_found_count   = 0
_error_count       = 0
_start_time        = time.time()


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
# Callbacks — accept an optional flag to count phase-1 separately
# -------------------------------------------------------------------

def _make_callbacks(cfg: dict, phase: int = 2):
    """
    phase=1  → increments recheck counters
    phase=2  → increments fresh counters
    Both phases increment the shared _found_total / _searches_done.
    """
    global _found_total, _searches_done, _not_found_count, _error_count
    global _recheck_searched, _recheck_found, _fresh_found, _fresh_searches

    def on_found(record: dict):
        global _found_total, _searches_done, _recheck_found, _fresh_found
        _found_total   += 1
        _searches_done += 1
        if phase == 1:
            _recheck_found += 1
        else:
            _fresh_found += 1
        save_found_report(record)
        sheets_handler.save_found(
            report_number    = str(record.get("reportNumber", "")),
            date_of_incident = str(record.get("dateOfIncident", "")),
        )

    def on_not_found(report_number: str):
        global _searches_done, _not_found_count, _recheck_searched, _fresh_searches
        _searches_done   += 1
        _not_found_count += 1
        if phase == 1:
            _recheck_searched += 1
        else:
            _fresh_searches += 1
        save_not_found_report(report_number)
        # Phase 1: do NOT write back to Not Found sheet — the entry is already there
        if phase == 2:
            sheets_handler.save_not_found(report_number)

    def on_error(report_number: str, error_msg: str):
        global _searches_done, _error_count
        _searches_done += 1
        _error_count   += 1
        print(f"   [ERROR FINAL] {report_number}: {error_msg[:80]}")
        sheets_handler.save_error(report_number, error_msg)
        save_not_found_report(f"ERROR:{report_number}")

    return on_found, on_not_found, on_error


# -------------------------------------------------------------------
# Pause helpers
# -------------------------------------------------------------------

def _countdown(label: str, seconds: int, interval: int = 30):
    for remaining in range(seconds, 0, -interval):
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

def _handle_all_slots_limit(cfg: dict, cursor, active_proxy: str) -> str:
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
# SAVE EXIT CURSOR — always call before exiting
# -------------------------------------------------------------------

def _save_exit_cursor(cursor: int):
    """Write next start number to Google Sheet A2 and log it."""
    print(f"\n   [PROGRESS] Saving next start number to sheet: {cursor}")
    sheets_handler.set_start_number(cursor)


# -------------------------------------------------------------------
# PHASE 1 — Re-check Not Found entries
# -------------------------------------------------------------------

def _run_phase1(cfg: dict) -> list:
    """
    Pull up to NOT_FOUND_RECHECK_LIMIT entries from the Not Found sheet
    and search them using the slot machinery.

    Returns a list of report number strings that were found this time
    so the caller can remove them from the Not Found sheet.
    """
    global _recheck_searched

    not_found_batch = sheets_handler.get_not_found_batch(NOT_FOUND_RECHECK_LIMIT)
    if not not_found_batch:
        print("\n[PHASE 1] Not Found sheet is empty — skipping re-check phase.")
        return []

    accounts        = cfg["accounts"]
    otp_timeout_min = cfg["otp_timeout_min"]
    target          = cfg["target"]

    on_found, on_not_found, on_error = _make_callbacks(cfg, phase=1)

    print(f"\n{'#'*60}")
    print(f"  PHASE 1 — Re-checking {len(not_found_batch)} Not Found entries")
    print(f"  Target so far: {_found_total}/{target}")
    print(f"{'#'*60}")

    newly_found_numbers = []
    active_proxy        = None
    last_active_slot    = None
    remaining           = list(not_found_batch)   # copy so we can slice into batches

    # We feed these through the normal slot machinery in BATCH_SIZE chunks
    while remaining and _found_total < target:
        if _check_timeout():
            return newly_found_numbers

        for slot_idx in range(TOTAL_SLOTS):
            if not remaining:
                break
            if _found_total >= target:
                break
            if _check_timeout():
                return newly_found_numbers

            batch = remaining[:BATCH_SIZE]

            print(f"\n{'='*60}")
            print(f"  [PHASE 1] {_slot_label(slot_idx, accounts)}")
            print(f"  Re-checking: {batch[0]} -> {batch[-1]}  |  Found: {_found_total}/{target}")
            print(f"{'='*60}")

            if last_active_slot is not None:
                _inter_slot_pause(last_active_slot, slot_idx, accounts)

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
                    mailer.send_otp_required(cfg, slot_idx, lbl,
                                             acc.get("username", ""), acc.get("password", ""))
                    sheets_handler.save_error(f"OTP_TIMEOUT_SLOT{slot_idx}",
                                              f"OTP timeout for {lbl}")
                elif "LOGIN_FAILED" in err:
                    print(f"\n   [LOGIN FAILED] {_slot_label(slot_idx, accounts)} — skipping")
                else:
                    print(f"\n   [SESSION ERROR] {_slot_label(slot_idx, accounts)}: {e}")
                last_active_slot = slot_idx
                continue

            # Wrap on_found so we also collect the report number for removal
            def on_found_phase1(record: dict, _nf_batch=batch):
                rn = str(record.get("reportNumber", ""))
                newly_found_numbers.append(rn)
                on_found(record)

            found_in_slot, _, status = run_slot_batch(
                slot_idx           = slot_idx,
                api_session        = api_session,
                report_numbers     = [int(r) for r in batch],
                found_callback     = on_found_phase1,
                not_found_callback = on_not_found,
                error_callback     = on_error,
                found_so_far       = _found_total,
                target             = target,
            )

            last_active_slot = slot_idx
            # Remove the processed batch from remaining regardless of status
            remaining = remaining[len(batch):]

            if status in ("control:stop", "control:restart", "consecutive_errors"):
                print(f"   [PHASE 1] Stopping early due to status: {status}")
                return newly_found_numbers

            if status == "limit":
                _limit_pause(slot_idx, 0, accounts)

        # If we've gone through all slots and there's still remaining,
        # loop back — the all-slots-limit logic is simpler here since
        # these are not sequential numbers, just exit phase 1
        if remaining:
            print(f"\n[PHASE 1] All slots exhausted. "
                  f"{len(remaining)} not-found entries left unchecked this run.")
            break

    print(f"\n[PHASE 1] Complete. "
          f"Re-checked={_recheck_searched + _recheck_found}, "
          f"Newly found={_recheck_found}")
    return newly_found_numbers


# -------------------------------------------------------------------
# PHASE 2 — Sequential fresh search (original _run logic)
# -------------------------------------------------------------------

def _run_phase2(cfg: dict, start_report: int) -> tuple:
    """
    Run the sequential fresh search until target is reached or an
    exit condition fires.

    Returns (outcome_string, last_cursor) where last_cursor is the
    next report number to use on the following run.
    """
    global _found_total, _searches_done, _not_found_count, _error_count

    accounts        = cfg["accounts"]
    target          = cfg["target"]
    otp_timeout_min = cfg["otp_timeout_min"]

    on_found, on_not_found, on_error = _make_callbacks(cfg, phase=2)

    current_report = start_report
    cycle_num      = 0
    active_proxy   = None
    last_cursor    = start_report

    print(f"\n{'#'*60}")
    print(f"  PHASE 2 — Fresh sequential search")
    print(f"  Target  : {target} valid reports ({_found_total} already found in Phase 1)")
    print(f"  Starting: report #{current_report}")
    print(f"  Accounts: {len(accounts)}")
    print(f"  Timeout : {_time_remaining_str()} remaining")
    print(f"{'#'*60}")

    while _found_total < target:

        if _check_timeout():
            _save_exit_cursor(current_report)
            mailer.send_crash(cfg,
                              Exception(f"Auto-terminated after {MAX_RUN_HOURS}h"),
                              _found_total, _searches_done, _elapsed())
            return "timeout", current_report

        cycle_num   += 1
        cursor       = current_report
        limit_count  = 0

        print(f"\n{'#'*60}")
        print(f"  CYCLE #{cycle_num:03d}  —  cursor={cursor}  found={_found_total}/{target}")
        print(f"  Active IP : {'proxy' if active_proxy else 'direct'}")
        print(f"  Time left : {_time_remaining_str()}")
        print(f"{'#'*60}")

        last_active_slot = None
        slots_attempted  = 0

        for slot_idx in range(TOTAL_SLOTS):

            if _check_timeout():
                _save_exit_cursor(cursor)
                mailer.send_crash(cfg,
                                  Exception(f"Auto-terminated after {MAX_RUN_HOURS}h"),
                                  _found_total, _searches_done, _elapsed())
                return "timeout", cursor

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
                else:
                    print(f"\n   [SESSION ERROR] {_slot_label(slot_idx, accounts)}: {e}")
                last_active_slot = slot_idx
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
            last_cursor      = next_report

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
                mailer.send_consecutive_errors(
                    cfg, str(next_report), "20 consecutive errors",
                    _found_total, _searches_done, _elapsed()
                )
                _save_exit_cursor(next_report)
                return "consecutive_errors", next_report

            elif status == "control:stop":
                mailer.send_user_stop(cfg, _found_total, _searches_done, _elapsed())
                _save_exit_cursor(next_report)
                return "stop", next_report

            elif status == "control:restart":
                mailer.send_restart(cfg, _found_total, _searches_done,
                                    _elapsed(), next_report)
                _save_exit_cursor(next_report)
                return "restart", next_report

            _save_exit_cursor(cursor)

            if _found_total >= target:
                break

        if _found_total >= target:
            break

        if slots_attempted > 0 and limit_count >= slots_attempted:
            active_proxy = _handle_all_slots_limit(cfg, cursor, active_proxy)
        else:
            current_report = cursor

        _save_exit_cursor(current_report)
        print(f"\nCycle #{cycle_num:03d} complete. Next from #{current_report}. "
              f"Found {_found_total}/{target} | IP: {'proxy' if active_proxy else 'direct'}")

    return "done", current_report


# -------------------------------------------------------------------
# FINAL SUMMARY PRINT
# -------------------------------------------------------------------

def _print_run_summary(target: int):
    print(f"\n{'='*60}")
    print(f"  RUN SUMMARY")
    print(f"{'='*60}")
    print(f"  Total found       : {_found_total} / {target}")
    print(f"  Total searches    : {_searches_done}")
    print(f"  Elapsed           : {mailer._fmt_elapsed(_elapsed())}")
    print(f"")
    print(f"  -- Phase 1 (Not Found re-checks) --")
    print(f"  Entries re-checked: {_recheck_searched + _recheck_found}")
    print(f"  Newly found       : {_recheck_found}")
    print(f"")
    print(f"  -- Phase 2 (Fresh sequential) --")
    print(f"  Searches done     : {_fresh_searches + _fresh_found}")
    print(f"  Found             : {_fresh_found}")
    print(f"  Not found         : {_not_found_count}")
    print(f"  Errors            : {_error_count}")
    print(f"{'='*60}")


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------

def main():
    global _found_total, _searches_done, _not_found_count, _error_count, _start_time
    global _recheck_searched, _recheck_found, _fresh_found, _fresh_searches

    parser = argparse.ArgumentParser(description="BuyCrash Report Automation")
    parser.add_argument("--reset", action="store_true",
                        help="Ignored (progress.txt removed). Kept for CLI compatibility.")
    parser.add_argument("--start", type=int,
                        help="Override start report number for Phase 2.")
    args = parser.parse_args()

    print("=" * 60)
    print("  BuyCrash Report Automation")
    print(f"  Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Timeout : auto-terminate after {MAX_RUN_HOURS}h")
    print("=" * 60)

    while True:
        # Reset all counters on every (re)start
        _found_total      = 0
        _searches_done    = 0
        _not_found_count  = 0
        _error_count      = 0
        _recheck_searched = 0
        _recheck_found    = 0
        _fresh_found      = 0
        _fresh_searches   = 0
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

        # ── Determine Phase 2 start number ───────────────────────────
        if args.start:
            start_report = args.start
            print(f"Start override from CLI: {start_report}")
        else:
            gs_start = sheets_handler.get_start_number()  # reads A2 and clears it
            if gs_start and gs_start > 0:
                start_report = gs_start
                print(f"Start from Google Sheet (A2): {start_report}")
            else:
                # Fallback: start from 1 if sheet is empty (first ever run)
                start_report = 1
                print(f"No start number in sheet — starting from {start_report}")

        print(f"\n  Accounts       : {len(cfg['accounts'])}")
        print(f"  Target         : {cfg['target']}")
        print(f"  Phase 2 start  : {start_report}")
        print(f"  NF recheck lim : {NOT_FOUND_RECHECK_LIMIT}")
        print(f"  OTP timeout    : {cfg['otp_timeout_min']} min")
        print(f"  Alert email    : {cfg.get('alert_email') or 'not set'}")
        print(f"  Batch size     : {BATCH_SIZE} / slot")
        print(f"  Consec. limit  : {CONSECUTIVE_ERROR_LIMIT} errors")
        print(f"  Proxy          : {'configured' if cfg.get('residential_proxy') else 'none'}")
        print(f"  Time remaining : {_time_remaining_str()}")
        print()

        outcome      = "crash"
        last_cursor  = start_report

        try:
            # ── PHASE 1: Re-check Not Found list ─────────────────────
            newly_found_from_nf = _run_phase1(cfg)

            # Remove the ones that turned into Found from Not Found sheet
            if newly_found_from_nf:
                print(f"\n[PHASE 1] Removing {len(newly_found_from_nf)} entries "
                      f"from Not Found sheet...")
                sheets_handler.remove_from_not_found(newly_found_from_nf)

            # ── PHASE 2: Fresh sequential search ─────────────────────
            if _found_total < cfg["target"]:
                outcome, last_cursor = _run_phase2(cfg, start_report)
            else:
                print(f"\n[PHASE 2] Skipped — target already reached in Phase 1.")
                outcome = "done"
                last_cursor = start_report

        except Exception as e:
            print(f"\n[CRASH] Unhandled exception: {e}")
            print(traceback.format_exc())
            mailer.send_crash(cfg, e, _found_total, _searches_done, _elapsed())
            _save_exit_cursor(last_cursor)
            outcome = "crash"

        # ── Always print the detailed summary ────────────────────────
        _print_run_summary(cfg["target"])

        if outcome == "done":
            print(f"\n[SUCCESS] {_found_total}/{cfg['target']} reports found")
            mailer.send_success(
                cfg, _found_total, cfg["target"],
                _searches_done, _elapsed(),
                _not_found_count, _error_count
            )
            get_summary()
            # On success, save last_cursor so next run continues from here
            _save_exit_cursor(last_cursor)
            break

        elif outcome == "restart":
            print(f"\n[RESTART] Pausing {RESTART_PAUSE_SEC // 60} min then restarting...")
            # last_cursor already saved inside _run_phase2 on restart signal
            time.sleep(RESTART_PAUSE_SEC)
            args.start = None
            print("[RESTART] Reloading config and starting over...\n")
            continue

        elif outcome == "timeout":
            print(f"\n[EXIT] Auto-terminated after {MAX_RUN_HOURS}h")
            # last_cursor already saved inside _run_phase2 on timeout
            get_summary()
            break

        elif outcome in ("stop", "consecutive_errors", "crash"):
            print(f"\n[EXIT] Reason: {outcome}")
            # last_cursor already saved for stop/consecutive_errors inside _run_phase2
            # for crash it's saved in the except block above
            get_summary()
            break


if __name__ == "__main__":
    main()