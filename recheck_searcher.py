"""
recheck_searcher.py
-------------------
Re-checks report numbers from the Not Found sheet using 12 dedicated accounts.

Key differences from normal searcher:
- No no-login slot — all 12 slots require login
- Reads report numbers from Not Found sheet instead of sequential range
- On found: writes to ReCheck Found sheet, removes from Not Found sheet
- Cursor stored in Start Number sheet B2
- Daily limit configured in Config sheet B66
- Rotates through accounts in batches of BATCH_SIZE (15)
- If all accounts hit limit: switches proxy (B34), same logic as main search
- Control cell B33 shared with normal search (stop / pause / restart)
"""

import time
import random
import requests

from config import (
    BASE_URL, SEARCH_PAGE_URL,
    CAPTCHA_API_KEY,
    SEARCH_DELAY_MIN, SEARCH_DELAY_MAX,
    CONSECUTIVE_ERROR_LIMIT,
    RECHECK_BATCH_SIZE,
    RECHECK_NUM_ACCOUNTS,
)
from searcher import (
    get_session_for_slot,
    solve_recaptcha,
    _search_via_api,
    _random_delay,
)


# -------------------------------------------------------------------
# RUN ONE RECHECK BATCH FOR ONE ACCOUNT SLOT
# -------------------------------------------------------------------

def run_recheck_slot_batch(
    slot_idx: int,
    api_session: requests.Session,
    report_numbers: list,
    found_callback,
    not_found_callback,
    error_callback,
    searches_done_so_far: int,
    daily_limit: int,
) -> tuple:
    """
    Returns (processed_count, last_report_number, status)

    status values:
      "ok"                 — batch completed normally
      "limit"              — SEARCH_LIMIT_REACHED
      "session"            — SESSION_EXPIRED mid-batch
      "consecutive_errors" — too many back-to-back errors
      "control:stop"
      "control:restart"
      "daily_limit"        — hit today's search quota
    """
    import sheets_handler

    MAX_RETRIES      = 3
    processed        = 0
    consecutive_errs = 0
    slot_label       = f"RECHECK-SLOT {slot_idx}"
    last_report      = report_numbers[-1] if report_numbers else None

    for i, report_num in enumerate(report_numbers):

        if searches_done_so_far + processed >= daily_limit:
            print(f"\n*** DAILY RECHECK LIMIT {daily_limit} REACHED ***")
            return processed, report_num, "daily_limit"

        report_str = str(report_num)
        print(f"\n{'='*52}")
        print(f"  [{slot_label}] Report: {report_str}  ({i+1}/{len(report_numbers)})")
        print(f"  Searches today: {searches_done_so_far + processed}/{daily_limit}")
        print(f"{'='*52}")

        # Control cell check
        cmd = sheets_handler.check_control()
        if cmd == "stop":
            return processed, report_num, "control:stop"
        elif cmd == "restart":
            return processed, report_num, "control:restart"
        elif cmd == "pause":
            print(f"   [CONTROL] PAUSE — sleeping 30 min...")
            for remaining in range(1800, 0, -30):
                m, s = divmod(remaining, 60)
                print(f"   [PAUSE] Resuming in {m}m {s:02d}s...  ", end="\r")
                time.sleep(30)
            print()
            print("   [CONTROL] Resuming after pause.")

        last_error = None
        success    = False

        for attempt in range(1, MAX_RETRIES + 1):
            if attempt > 1:
                print(f"   [RETRY] Attempt {attempt}/{MAX_RETRIES}...")
                time.sleep(5)

            try:
                token  = solve_recaptcha(SEARCH_PAGE_URL)
                result = _search_via_api(api_session, report_str, token)

                if result is not None:
                    consecutive_errs = 0
                    found_callback(result)
                    print(f"   [{slot_label}] FOUND (was in Not Found list): {report_str}")
                else:
                    consecutive_errs = 0
                    not_found_callback(report_str)

                success = True
                break

            except Exception as e:
                err        = str(e)
                last_error = err

                if "SEARCH_LIMIT_REACHED" in err:
                    print(f"   [{slot_label}] SEARCH_LIMIT_REACHED on {report_str}")
                    return processed, report_num, "limit"

                if "SESSION_EXPIRED" in err:
                    print(f"   [{slot_label}] Session expired on {report_str}")
                    return processed, report_num, "session"

                if "CAPTCHA_API_KEY" in err:
                    raise

                print(f"   [ERROR] Attempt {attempt}/{MAX_RETRIES}: {err[:120]}")

        if not success:
            consecutive_errs += 1
            print(f"   [ERROR] All retries failed for {report_str} "
                  f"(consecutive: {consecutive_errs}/{CONSECUTIVE_ERROR_LIMIT})")
            if error_callback:
                error_callback(report_str, last_error or "Unknown error")

            if consecutive_errs >= CONSECUTIVE_ERROR_LIMIT:
                print(f"\n[FATAL] {CONSECUTIVE_ERROR_LIMIT} consecutive errors — stopping recheck")
                return processed, report_num, "consecutive_errors"
        else:
            consecutive_errs = 0

        processed += 1

        if i < len(report_numbers) - 1:
            _random_delay()

    return processed, last_report, "ok"