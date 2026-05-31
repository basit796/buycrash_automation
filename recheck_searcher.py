"""
recheck_searcher.py
-------------------
Re-checks report numbers from the Not Found sheet using 12 dedicated accounts.

Key differences from normal searcher:
- No no-login slot — all 12 slots require login
- Cookie files prefixed "recheck_" — never collides with normal search cookies
- OTP handled automatically via Mail.tm token (same as normal search)
- Reads report numbers from Not Found sheet instead of sequential range
- On found: writes to ReCheck Found sheet, removes from Not Found sheet
- Daily limit tracked via shared counters dict (no target logic)
"""

import os
import time
import pickle
import requests

from config import (
    SEARCH_PAGE_URL,
    CONSECUTIVE_ERROR_LIMIT,
    RECHECK_BATCH_SIZE,
)
from searcher import (
    solve_recaptcha,
    _search_via_api,
    _random_delay,
    _login_via_browser,
    _build_api_session,
    _test_session,
)


# -------------------------------------------------------------------
# RECHECK-SPECIFIC COOKIE HELPERS
# Prefixed "recheck_" so they never collide with normal search cookies
# (session_cookies_slot0.pkl etc).
# -------------------------------------------------------------------

def _recheck_cookie_file(slot_idx: int) -> str:
    return f"recheck_session_cookies_slot{slot_idx}.pkl"


def _save_recheck_cookies(slot_idx: int, data: dict):
    with open(_recheck_cookie_file(slot_idx), "wb") as f:
        pickle.dump(data, f)
    print(f"   [RECHECK SLOT {slot_idx}] Cookies saved.")


def _load_recheck_cookies(slot_idx: int) -> dict:
    path = _recheck_cookie_file(slot_idx)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    return {}


def _delete_recheck_cookies(slot_idx: int):
    path = _recheck_cookie_file(slot_idx)
    if os.path.exists(path):
        os.remove(path)
        print(f"   [RECHECK SLOT {slot_idx}] Cookies deleted.")


# -------------------------------------------------------------------
# GET SESSION FOR RECHECK SLOT
# Same logic as searcher.get_session_for_slot but:
#   - uses recheck_ cookie files (no collision with normal search)
#   - passes mailtm_token so OTP is handled automatically
# -------------------------------------------------------------------

def get_recheck_session(slot_idx: int, accounts: list,
                        otp_timeout_min: int,
                        proxy: str = None,
                        mailtm_tokens: list = None) -> requests.Session:
    """
    Returns an authenticated requests.Session for the given recheck slot.
    Reuses saved recheck cookies if still valid, otherwise re-logs in.
    OTP is handled automatically via Mail.tm token from mailtm_tokens[slot_idx].
    """
    if slot_idx >= len(accounts):
        raise Exception(f"LOGIN_FAILED: no recheck account for slot {slot_idx}")

    account      = accounts[slot_idx]
    mailtm_token = (
        mailtm_tokens[slot_idx]
        if mailtm_tokens and slot_idx < len(mailtm_tokens)
        else None
    ) or None

    # Try cached recheck cookies first
    saved = _load_recheck_cookies(slot_idx)
    if saved:
        cookie_dict     = saved.get("cookies", {})
        ua              = saved.get("user_agent")
        saved_proxy     = saved.get("proxy")
        proxy_unchanged = (saved_proxy == proxy)
        if cookie_dict and proxy_unchanged:
            api_session = _build_api_session(cookie_dict, ua, proxy)
            if _test_session(api_session, slot_idx):
                return api_session
        print(f"   [RECHECK SLOT {slot_idx}] Session expired or proxy changed — re-logging in")
        _delete_recheck_cookies(slot_idx)

    # _login_via_browser handles OTP automatically when mailtm_token is set
    # (it calls _handle_otp → wait_for_otp from mailreader.py internally)
    cookie_dict = _login_via_browser(
        slot_idx        = slot_idx,
        account         = account,
        otp_timeout_min = otp_timeout_min,
        proxy           = proxy,
        mailtm_token    = mailtm_token,
    )
    if not cookie_dict:
        raise Exception(f"LOGIN_FAILED for recheck slot {slot_idx}")

    # Re-read to get user_agent that was saved by _login_via_browser_inner
    saved = _load_recheck_cookies(slot_idx)
    ua    = saved.get("user_agent") if saved else None
    _save_recheck_cookies(slot_idx, {"cookies": cookie_dict, "user_agent": ua, "proxy": proxy})
    return _build_api_session(cookie_dict, ua, proxy)


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
    counters: dict,
    daily_limit: int,
) -> tuple:
    """
    Returns (processed_count, last_processed_report, status)

    counters is the single shared dict {"searches": N, "found": N, "errors": N}.
    Callbacks increment counters["searches"] so the daily_limit check here
    is always the exact live count — correct for found, not-found, AND error.

    status values:
      "ok"                 — batch completed normally
      "limit"              — SEARCH_LIMIT_REACHED
      "session"            — SESSION_EXPIRED mid-batch
      "consecutive_errors" — too many back-to-back errors
      "daily_limit"        — hit today's search quota
      "control:stop"
      "control:restart"
    """
    import sheets_handler

    MAX_RETRIES      = 3
    processed        = 0
    consecutive_errs = 0
    slot_label       = f"RECHECK-SLOT {slot_idx}"
    last_processed   = None

    for i, report_num in enumerate(report_numbers):

        # Live daily-limit check — counters updated by callbacks so always exact
        if counters["searches"] >= daily_limit:
            print(f"\n*** DAILY RECHECK LIMIT {daily_limit} REACHED ***")
            return processed, report_num, "daily_limit"

        report_str = str(report_num)
        print(f"\n{'='*52}")
        print(f"  [{slot_label}] Report: {report_str}  ({i+1}/{len(report_numbers)})")
        print(f"  Searches today: {counters['searches']}/{daily_limit}")
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
                    found_callback(result)   # increments counters["searches"] + ["found"]
                    print(f"   [{slot_label}] FOUND (was in Not Found list): {report_str}")
                else:
                    consecutive_errs = 0
                    not_found_callback(report_str)   # increments counters["searches"]

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
            error_callback(report_str, last_error or "Unknown error")  # increments counters

            if consecutive_errs >= CONSECUTIVE_ERROR_LIMIT:
                print(f"\n[FATAL] {CONSECUTIVE_ERROR_LIMIT} consecutive errors — stopping recheck")
                return processed, report_num, "consecutive_errors"
        else:
            consecutive_errs = 0

        processed      += 1
        last_processed  = report_num

        if i < len(report_numbers) - 1:
            _random_delay()

    return processed, last_processed or (report_numbers[-1] if report_numbers else None), "ok"