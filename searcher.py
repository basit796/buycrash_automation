"""
searcher.py
-----------
Handles browser login, session management, captcha solving,
and the per-report API search.

Slot model (defined in config.py):
  Slot 0,1,2  — logged-in accounts (ACCOUNTS[0..2])
  Slot 3      — no-login (direct URL, no credentials)

Key change: run_slot_batch now returns (found_count, next_report, status)
  next_report = the report number to continue from (accounts for mid-batch stops)
"""
import os
import re
import time
import random
import pickle
import requests
from seleniumbase import SB
from config import (
    ACCOUNTS, NO_LOGIN_SLOT,
    BASE_URL, SEARCH_PAGE_URL, SEARCH_API_URL,
    STATE, JURISDICTION,
    get_report_type_label,
    CAPTCHA_API_KEY, CAPTCHA_SITE_KEY,
    SEARCH_DELAY_MIN, SEARCH_DELAY_MAX,
    OTP_WAIT_SEC,
)


# -------------------------------------------------------------------
# LIVE SITE KEY  (extracted from page; falls back to config value)
# -------------------------------------------------------------------

# Module-level cache — refreshed every time a browser session opens
_live_site_key: str = None


def _extract_site_key_from_browser(sb) -> str:
    """
    Try to read the reCAPTCHA site key directly from the live page.
    Attempts:
      1. data-sitekey attribute on any element
      2. Regex scan of full page HTML for a reCAPTCHA key pattern
    Returns the key string, or None if not found.
    """
    # Method 1: data-sitekey attribute
    try:
        key = sb.cdp.evaluate("""
            (function() {
                var el = document.querySelector('[data-sitekey]');
                return el ? el.getAttribute('data-sitekey') : null;
            })()
        """)
        if key and len(str(key)) > 20:
            return str(key).strip()
    except Exception:
        pass

    # Method 2: regex in full page source
    try:
        html = sb.cdp.get_page_source()
        match = re.search(r'6[A-Za-z0-9_-]{38,42}', html)
        if match:
            return match.group(0)
    except Exception:
        pass

    return None


def _refresh_site_key(sb):
    """Called after the browser loads the search page to update the cached key."""
    global _live_site_key
    found = _extract_site_key_from_browser(sb)
    if found:
        if found != _live_site_key:
            print(f"   [CAPTCHA] Site key updated: {found[:30]}...")
        _live_site_key = found
    else:
        print(f"   [CAPTCHA] Could not extract live site key — using config fallback")


def get_active_site_key() -> str:
    """Return the most recently extracted live key, or the config fallback."""
    return _live_site_key or CAPTCHA_SITE_KEY


# -------------------------------------------------------------------
# COOKIE PERSISTENCE  (one file per slot)
# -------------------------------------------------------------------

def _cookie_file(slot_idx: int) -> str:
    return f"session_cookies_slot{slot_idx}.pkl"


def _save_cookies(slot_idx: int, data: dict):
    with open(_cookie_file(slot_idx), "wb") as f:
        pickle.dump(data, f)
    print(f"   [SLOT {slot_idx}] Cookies saved.")


def _load_cookies(slot_idx: int) -> dict:
    path = _cookie_file(slot_idx)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    return {}


def _delete_cookies(slot_idx: int):
    path = _cookie_file(slot_idx)
    if os.path.exists(path):
        os.remove(path)
        print(f"   [SLOT {slot_idx}] Cookies deleted.")


# -------------------------------------------------------------------
# SESSION VALIDATION
# -------------------------------------------------------------------

def _test_session(api_session: requests.Session, slot_idx: int) -> bool:
    try:
        resp = api_session.get(
            f"{BASE_URL}/gateway/nossop/session/user", timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("loginId"):
                print(f"   [SLOT {slot_idx}] Session valid — {data.get('loginId')}")
                return True
        print(f"   [SLOT {slot_idx}] Session check: HTTP {resp.status_code}")
        return False
    except Exception as e:
        print(f"   [SLOT {slot_idx}] Session check error: {e}")
        return False


# -------------------------------------------------------------------
# BUILD requests.Session FROM COOKIE DICT
# -------------------------------------------------------------------

def _build_api_session(cookie_dict: dict, user_agent: str = None) -> requests.Session:
    session = requests.Session()
    for name, value in cookie_dict.items():
        session.cookies.set(name, value, domain="buycrash.lexisnexisrisk.com")

    ua = user_agent or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    )
    xsrf = cookie_dict.get("XSRF-TOKEN", "")
    session.headers.update({
        "User-Agent":          ua,
        "Content-Type":        "application/json",
        "Accept":              "application/json, text/plain, */*",
        "Accept-Language":     "en",
        "Referer":             SEARCH_PAGE_URL,
        "Origin":              BASE_URL,
        "lnbc-client-version": "1.0.145",
        "x-xsrf-token":        xsrf,
    })
    if xsrf:
        print(f"   API session built — XSRF: {xsrf[:20]}...")
    else:
        print("   WARNING: XSRF-TOKEN missing — API may reject requests")
    return session


# -------------------------------------------------------------------
# EXTRACT COOKIES FROM BROWSER
# -------------------------------------------------------------------

def _extract_cookies(sb) -> dict:
    cookie_dict = {}
    try:
        for c in sb.cdp.get_all_cookies():
            name  = c.name  if hasattr(c, "name")  else c.get("name", "")
            value = c.value if hasattr(c, "value") else c.get("value", "")
            if name and value:
                cookie_dict[name] = value
        print(f"   Extracted {len(cookie_dict)} cookies: {list(cookie_dict.keys())}")
    except Exception as e:
        print(f"   Cookie extraction error: {e}")
    return cookie_dict


# -------------------------------------------------------------------
# OTP HANDLER
# -------------------------------------------------------------------

def _handle_otp(sb, slot_idx: int, account_label: str) -> bool:
    """
    Attempt to complete OTP flow by reading code from Google Sheet B2.
    Waits up to OTP_WAIT_SEC seconds.
    Returns True if OTP completed, False if timed out.
    """
    import sheets_handler

    wait_sec = OTP_WAIT_SEC
    print("")
    print("=" * 60)
    print(f"  OTP REQUIRED — Slot {slot_idx} ({account_label})")
    print(f"  Waiting up to {wait_sec // 60} min for OTP in Sheet B2")
    print(f"  *** Paste OTP for [{account_label}] into cell B2 ***")
    print("=" * 60)

    for sel in ["input[type='radio'][value*='mail']", "input[type='radio']:first-of-type"]:
        try:
            sb.cdp.click(sel)
            break
        except Exception:
            continue
    sb.sleep(1)

    for sel in ["button:contains('Send Code')", "button:contains('Continue')", "button[type='submit']"]:
        try:
            sb.cdp.click(sel)
            print("   Clicked Send Code")
            break
        except Exception:
            continue
    sb.sleep(2)

    elapsed  = 0
    interval = 30
    otp_code = None

    while elapsed < wait_sec:
        sb.sleep(interval)
        elapsed   += interval
        remaining  = wait_sec - elapsed
        print(f"   [OTP] {elapsed}s elapsed, {remaining}s remaining")
        try:
            code = sheets_handler.get_otp_from_sheet()
            if code:
                otp_code = str(code).strip()
                print(f"   [OTP] Received: {otp_code}")
                sheets_handler.clear_otp_from_sheet()
                break
        except Exception as e:
            print(f"   [OTP] Sheet poll error: {e}")

    if not otp_code:
        print(f"   [OTP] Timeout — no OTP for slot {slot_idx} ({account_label})")
        return False

    for _ in range(15):
        sb.sleep(1)
        try:
            body = sb.cdp.get_text("body")
            if "Verify Authentication" in body or "Passcode" in body:
                break
        except Exception:
            pass

    sb.sleep(1)
    filled = False

    for sel in [
        "input[name*='passcode']", "input[id*='passcode']",
        "input[name*='Passcode']", "input[id*='Passcode']",
        "input[name*='otp']",      "input[name*='code']",
        "input[placeholder*='asscode']",
    ]:
        try:
            sb.cdp.click(sel)
            sb.sleep(0.2)
            sb.cdp.evaluate(f"document.querySelector('{sel}').value = ''")
            sb.cdp.type(sel, otp_code)
            filled = True
            break
        except Exception:
            continue

    if not filled:
        try:
            sb.cdp.evaluate(f"""
                (function() {{
                    var inputs = document.querySelectorAll(
                        'input[type="text"], input[type="password"], input:not([type])'
                    );
                    for (var i = 0; i < inputs.length; i++) {{
                        if (inputs[i].offsetParent !== null) {{
                            inputs[i].focus();
                            inputs[i].value = '{otp_code}';
                            inputs[i].dispatchEvent(new Event('input', {{bubbles:true}}));
                            inputs[i].dispatchEvent(new Event('change', {{bubbles:true}}));
                            break;
                        }}
                    }}
                }})();
            """)
            filled = True
        except Exception as e:
            print(f"   [OTP] JS fill failed: {e}")

    if not filled:
        print("   [OTP] Could not fill passcode field")
        return False

    sb.sleep(0.5)
    for btn in ["button:contains('Submit')", "button[type='submit']", "input[type='submit']"]:
        try:
            sb.cdp.click(btn)
            break
        except Exception:
            continue

    sb.sleep(4)
    print("   [OTP] Submitted successfully")
    return True


# -------------------------------------------------------------------
# LOGIN VIA BROWSER  (slots 0-2)
# -------------------------------------------------------------------

def _login_via_browser(slot_idx: int) -> dict:
    """
    Log in using ACCOUNTS[slot_idx]. Handle OTP if needed.
    Also refreshes the live site key while browser is open.
    Returns cookie dict, or empty dict on failure.
    Raises Exception("OTP_TIMEOUT") if OTP screen appears but times out.
    """
    account       = ACCOUNTS[slot_idx]
    username      = account["username"]
    password      = account["password"]
    account_label = f"Account {slot_idx + 1}: {username}"
    cookie_dict   = {}
    user_agent    = None

    print(f"\n   [SLOT {slot_idx}] Logging in as {username}...")

    with SB(uc=True, test=False, locale="en", headless=True) as sb:
        sb.activate_cdp_mode(BASE_URL + "/ui/home")
        sb.sleep(4)

        for strategy in [
            lambda: sb.cdp.find_element_by_text("Sign In").click(),
            lambda: sb.cdp.click("button:contains('Sign In')"),
            lambda: sb.cdp.gui_click_element("button:contains('Sign In')"),
        ]:
            try:
                strategy()
                print("   Clicked Sign In")
                break
            except Exception:
                continue
        sb.sleep(2)

        for sel in ["input[placeholder='User ID']", "input[name='username']", "input[type='text']"]:
            try:
                sb.cdp.click(sel)
                sb.sleep(0.3)
                sb.cdp.type(sel, username)
                break
            except Exception:
                continue
        sb.sleep(0.5)

        for sel in ["input[placeholder='Password']", "input[name='password']", "input[type='password']"]:
            try:
                sb.cdp.click(sel)
                sb.sleep(0.3)
                sb.cdp.type(sel, password)
                break
            except Exception:
                continue
        sb.sleep(0.5)

        submitted = False
        for sel in ["input[placeholder='Password']", "input[name='password']", "input[type='password']"]:
            try:
                sb.cdp.click(sel)
                sb.sleep(0.2)
                sb.cdp.press_keys(sel, "\n")
                submitted = True
                break
            except Exception:
                continue

        if not submitted:
            for strategy in [
                lambda: sb.cdp.find_element_by_text("Sign In").click(),
                lambda: sb.cdp.gui_click_element("button[type='submit']"),
                lambda: sb.cdp.click("button[type='submit']"),
            ]:
                try:
                    strategy()
                    break
                except Exception:
                    continue
        sb.sleep(6)

        url = sb.cdp.get_current_url()
        print(f"   URL after login: {url}")
        if "otp" in url.lower():
            otp_ok = _handle_otp(sb, slot_idx, account_label)
            if not otp_ok:
                raise Exception("OTP_TIMEOUT")

        try:
            body = sb.cdp.get_text("body")
            if "User ID" in body and "Sign In" in body[:500]:
                print(f"   [SLOT {slot_idx}] Still on login page — wrong credentials?")
                return {}
        except Exception:
            pass

        sb.cdp.open(SEARCH_PAGE_URL)
        sb.sleep(5)
        current_url = sb.cdp.get_current_url()
        if "search" not in current_url.lower():
            print(f"   [SLOT {slot_idx}] Did not reach search page after login")
            return {}

        # Refresh live site key while browser is on the search page
        _refresh_site_key(sb)

        cookie_dict = _extract_cookies(sb)
        try:
            user_agent = sb.cdp.get_user_agent()
        except Exception:
            pass

    if cookie_dict:
        _save_cookies(slot_idx, {"cookies": cookie_dict, "user_agent": user_agent})

    return cookie_dict


# -------------------------------------------------------------------
# NO-LOGIN SESSION  (slot 3)
# -------------------------------------------------------------------

def _get_no_login_session() -> requests.Session:
    """Navigate directly to the search page without logging in."""
    cookie_dict = {}
    user_agent  = None

    with SB(uc=True, test=False, locale="en", headless=True) as sb:
        print("   [SLOT 3 / NO-LOGIN] Navigating directly to search page...")
        sb.activate_cdp_mode(SEARCH_PAGE_URL)
        sb.sleep(5)
        print(f"   URL: {sb.cdp.get_current_url()}")

        # Refresh live site key while browser is on the search page
        _refresh_site_key(sb)

        cookie_dict = _extract_cookies(sb)
        try:
            user_agent = sb.cdp.get_user_agent()
        except Exception:
            pass

    if not cookie_dict:
        raise Exception("NO-LOGIN: Could not obtain cookies from search page")

    return _build_api_session(cookie_dict, user_agent)


# -------------------------------------------------------------------
# GET SESSION FOR SLOT
# -------------------------------------------------------------------

def get_session_for_slot(slot_idx: int) -> requests.Session:
    """
    Returns an authenticated requests.Session for the given slot.
      Slot 0-2 : logged-in account
      Slot 3   : no-login

    Raises:
      Exception("OTP_TIMEOUT")  if OTP screen appeared but timed out
      Exception("LOGIN_FAILED") if login could not be completed
    """
    if slot_idx == NO_LOGIN_SLOT:
        return _get_no_login_session()

    saved = _load_cookies(slot_idx)
    if saved:
        cookie_dict = saved.get("cookies", {})
        ua          = saved.get("user_agent")
        if cookie_dict:
            api_session = _build_api_session(cookie_dict, ua)
            if _test_session(api_session, slot_idx):
                return api_session
            print(f"   [SLOT {slot_idx}] Saved session expired — re-logging in")
            _delete_cookies(slot_idx)

    cookie_dict = _login_via_browser(slot_idx)
    if not cookie_dict:
        raise Exception(f"LOGIN_FAILED for slot {slot_idx}")

    saved = _load_cookies(slot_idx)
    ua    = saved.get("user_agent") if saved else None
    return _build_api_session(cookie_dict, ua)


# -------------------------------------------------------------------
# CAPTCHA  — always uses the live site key with config as fallback
# -------------------------------------------------------------------

def solve_recaptcha(page_url: str) -> str:
    if not CAPTCHA_API_KEY:
        raise Exception("CAPTCHA_API_KEY missing in .env")

    site_key = get_active_site_key()
    print(f"   Submitting CAPTCHA (site key: {site_key[:20]}...)")

    resp = requests.post("http://2captcha.com/in.php", data={
        "key":       CAPTCHA_API_KEY,
        "method":    "userrecaptcha",
        "googlekey": site_key,          # live key, not hardcoded
        "pageurl":   page_url,
        "json":      1,
    }, timeout=30)

    r = resp.json()
    if r.get("status") != 1:
        raise Exception(f"2Captcha submit error: {r}")

    task_id = r["request"]
    print(f"   Task {task_id} — waiting...")

    for attempt in range(24):
        time.sleep(12)
        poll = requests.get("http://2captcha.com/res.php", params={
            "key": CAPTCHA_API_KEY, "action": "get",
            "id": task_id, "json": 1,
        }, timeout=30)
        r = poll.json()
        if r.get("status") == 1:
            token = r["request"]
            print(f"   CAPTCHA solved (len={len(token)})")
            return token
        elif r.get("request") == "CAPCHA_NOT_READY":
            print(f"   Not ready... ({(attempt+1)*12}s)")
        else:
            raise Exception(f"2Captcha poll error: {r}")

    raise Exception("2Captcha timeout after 4 minutes")


# -------------------------------------------------------------------
# SINGLE REPORT SEARCH VIA API
# -------------------------------------------------------------------

def _search_via_api(api_session: requests.Session,
                    report_number: str,
                    captcha_token: str) -> dict:
    """
    Returns record dict if found, None if not found.
    Raises Exception("SESSION_EXPIRED") on 401/403.
    Raises Exception("SEARCH_LIMIT_REACHED") on rate limit.
    """
    payload = {
        "fields": {
            "state": STATE, "jurisdiction": JURISDICTION,
            "firstName": "", "lastName": "",
            "dateOfLoss": "", "accidentLocation1": "",
            "accidentLocation2": "", "reportNumber": report_number,
        },
        "captchaToken": captcha_token,
        "page": 1,
    }

    print(f"   [DEBUG] POST report={report_number} token_len={len(captcha_token)}")
    resp = api_session.post(SEARCH_API_URL, json=payload, timeout=30)
    print(f"   [DEBUG] HTTP {resp.status_code} | {resp.text[:300]}")

    if resp.status_code == 200:
        data = resp.json()
        code = data.get("code", "")

        if code == "SEARCH_LIMIT_REACHED":
            raise Exception("SEARCH_LIMIT_REACHED")

        if code == "VALIDATION_ERROR":
            msgs = data.get("validationMessages", [])
            print(f"   [DEBUG] Validation errors: {msgs}")
            return None

        if code == "OK":
            records = data.get("data", {}).get("records", [])
            print(f"   [DEBUG] Record groups: {len(records)}")

            real_record = None
            for group in reversed(records):
                if group and group[0].get("reportNumber") is not None:
                    real_record = group[0]
                    break

            if real_record:
                real_record["reportTypeLabel"] = get_report_type_label(
                    real_record.get("reportType") or "U"
                )
                return real_record

            print("   [DEBUG] No usable record — not found")
            return None

        print(f"   [DEBUG] Unexpected code: {code}")
        return None

    elif resp.status_code in (401, 403):
        raise Exception("SESSION_EXPIRED")
    else:
        print(f"   [DEBUG] Unexpected HTTP {resp.status_code}")
        return None


# -------------------------------------------------------------------
# INTER-SEARCH RANDOM DELAY
# -------------------------------------------------------------------

def _random_delay():
    delay = random.uniform(SEARCH_DELAY_MIN, SEARCH_DELAY_MAX)
    print(f"   [DELAY] {delay:.1f}s before next search...")
    time.sleep(delay)


# -------------------------------------------------------------------
# RUN A BATCH FOR ONE SLOT
# -------------------------------------------------------------------

def run_slot_batch(slot_idx: int,
                   api_session: requests.Session,
                   report_numbers: list,
                   found_callback,
                   not_found_callback,
                   error_callback,
                   found_so_far: int,
                   target: int) -> tuple:
    """
    Search report_numbers using api_session.

    Returns (found_count, next_report, status) where:
      found_count  — number of reports found in this batch
      next_report  — the report number to resume from next
                     (= exactly where we stopped, NOT start + BATCH_SIZE)
      status       — "ok"      completed the full batch normally
                   | "limit"   SEARCH_LIMIT_REACHED mid-batch
                   | "session" SESSION_EXPIRED mid-batch

    This means if slot hits limit on report #4 out of 15,
    next_report = report_numbers[3] so the next slot
    continues from that exact report, not report 16.
    """
    MAX_RETRIES = 3
    found_count = 0
    slot_label  = f"SLOT {slot_idx}" if slot_idx < NO_LOGIN_SLOT else "SLOT 3/NO-LOGIN"

    # Default: if we complete everything, next slot starts after this batch
    next_report = report_numbers[-1] + 1

    for i, report_num in enumerate(report_numbers):

        if found_so_far + found_count >= target:
            print(f"\n*** TARGET REACHED — stopping slot {slot_idx} early ***")
            next_report = report_num   # resume here if needed
            break

        report_str = str(report_num)
        print(f"\n{'='*52}")
        print(f"  [{slot_label}] Report: {report_str}  "
              f"({i+1}/{len(report_numbers)} in this slot)")
        print(f"{'='*52}")

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
                    found_count += 1
                    found_callback(result)
                    print(f"   [{slot_label}] Found: {found_count} | "
                          f"Global: {found_so_far + found_count}/{target}")
                    if found_so_far + found_count >= target:
                        print(f"\n*** GLOBAL TARGET {target} REACHED ***")
                        next_report = report_num + 1
                        return found_count, next_report, "ok"
                else:
                    not_found_callback(report_str)

                success = True
                break

            except Exception as e:
                err        = str(e)
                last_error = err

                if "SEARCH_LIMIT_REACHED" in err:
                    print(f"   [{slot_label}] SEARCH_LIMIT_REACHED on report "
                          f"{report_str} (#{i+1}/{len(report_numbers)})")
                    print(f"   [{slot_label}] Next slot will resume from {report_str}")
                    # next_report = THIS report so it gets retried by the next slot
                    return found_count, report_num, "limit"

                if "SESSION_EXPIRED" in err:
                    print(f"   [{slot_label}] Session expired on report {report_str}")
                    return found_count, report_num, "session"

                if "CAPTCHA_API_KEY" in err:
                    raise   # fatal — propagate up

                print(f"   [ERROR] Attempt {attempt}/{MAX_RETRIES}: {err[:120]}")

        if not success:
            print(f"   [ERROR] All retries failed for {report_str}")
            if error_callback:
                error_callback(report_str, last_error or "Unknown error")
            else:
                not_found_callback(report_str)
            # On generic failure we move on to the next report (don't stall the slot)

        # Inter-search delay (skip after last report in batch)
        if i < len(report_numbers) - 1:
            _random_delay()

    return found_count, next_report, "ok"