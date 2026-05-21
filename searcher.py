"""
searcher.py
-----------
Architecture: Single-account login mode.
  1. Login ONCE via browser UI  ->  extract session cookies
  2. Build a requests.Session with those cookies + correct headers
  3. For each report: solve captcha via 2Captcha -> POST to API directly
  4. Parse clean JSON response (no page scraping needed)
  5. Save cookies to disk so next run skips login if session still alive

Rate-limit strategy:
  - Batch size: 20 reports
  - 20-minute pause between every batch
  - On SEARCH_LIMIT_REACHED: pause 10 min, refresh session, retry — forever
    (never terminates due to rate limit alone)
  - Slower searches with random delay between each report
"""
import os
import time
import random
import json
import pickle
import requests
from seleniumbase import SB
from config import (
    USERNAME, PASSWORD_B64,
    BASE_URL, SEARCH_PAGE_URL, SEARCH_API_URL,
    STATE, JURISDICTION,
    get_report_type_label,
    CAPTCHA_API_KEY, CAPTCHA_SITE_KEY,
)

COOKIES_FILE = "session_cookies_1.pkl"   # single account → always slot 1


# -------------------------------------------------------------------
# COOKIE PERSISTENCE
# -------------------------------------------------------------------

def save_cookies(data: dict):
    with open(COOKIES_FILE, "wb") as f:
        pickle.dump(data, f)
    print(f"   Session cookies saved to {COOKIES_FILE}")


def load_cookies() -> dict:
    if os.path.exists(COOKIES_FILE):
        with open(COOKIES_FILE, "rb") as f:
            return pickle.load(f)
    return {}


def delete_cookies():
    if os.path.exists(COOKIES_FILE):
        os.remove(COOKIES_FILE)
        print(f"   Deleted saved cookies")


# -------------------------------------------------------------------
# SESSION VALIDATION
# -------------------------------------------------------------------

def _test_session(api_session: requests.Session) -> bool:
    """Quick check — call session/user endpoint."""
    try:
        resp = api_session.get(
            f"{BASE_URL}/gateway/nossop/session/user",
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("loginId"):
                print(f"   Session valid — logged in as: {data.get('loginId')}")
                return True
        print(f"   Session check returned {resp.status_code}: {resp.text[:100]}")
        return False
    except Exception as e:
        print(f"   Session check error: {e}")
        return False


# -------------------------------------------------------------------
# BUILD requests.Session FROM COOKIE DICT
# -------------------------------------------------------------------

def _build_api_session(cookie_dict: dict, user_agent: str = None) -> requests.Session:
    """
    Create a requests.Session pre-loaded with auth cookies.
    Sets x-xsrf-token header from the XSRF-TOKEN cookie (required for every POST).
    """
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

    print(f"   API session built — XSRF token: {xsrf[:20]}..." if xsrf else
          "   WARNING: XSRF-TOKEN cookie missing — API may reject requests")
    return session


# -------------------------------------------------------------------
# EXTRACT COOKIES FROM BROWSER
# -------------------------------------------------------------------

def _extract_cookies_from_browser(sb) -> dict:
    """Pull all cookies from the SeleniumBase browser into a plain dict."""
    cookie_dict = {}
    try:
        raw = sb.cdp.get_all_cookies()
        for c in raw:
            name  = c.name  if hasattr(c, "name")  else c.get("name", "")
            value = c.value if hasattr(c, "value") else c.get("value", "")
            if name and value:
                cookie_dict[name] = value
        print(f"   Extracted {len(cookie_dict)} cookies: {list(cookie_dict.keys())}")
    except Exception as e:
        print(f"   Cookie extraction error: {e}")
    return cookie_dict


# -------------------------------------------------------------------
# OTP HANDLER — reads code from Google Sheet cell B2
# -------------------------------------------------------------------

def _handle_otp(sb):
    """
    Full OTP flow:
    1. Select Email radio
    2. Click 'Send Code and Continue'
    3. Poll Google Sheet Start Number!B2 for the OTP (user pastes it there)
    4. Fill the Passcode field and submit
    """
    import sheets_handler

    print("")
    print("=" * 55)
    print("  OTP REQUIRED — Unrecognized Location")
    print("=" * 55)

    # Step 1: Select Email radio
    print("   Selecting Email as OTP channel...")
    for sel in [
        "input[type='radio'][value*='mail']",
        "input[type='radio']:first-of-type",
    ]:
        try:
            sb.cdp.click(sel)
            print("   Email radio selected")
            break
        except Exception:
            continue

    sb.sleep(1)

    # Step 2: Click Send Code and Continue
    print("   Clicking 'Send Code and Continue'...")
    for sel in [
        "button:contains('Send Code')",
        "button:contains('Continue')",
        "button[type='submit']",
    ]:
        try:
            sb.cdp.click(sel)
            print("   Clicked Send Code button")
            break
        except Exception:
            continue

    sb.sleep(2)

    # Step 3: Poll Google Sheet for OTP
    print("")
    print("-" * 55)
    print("  ACTION REQUIRED:")
    print("  An OTP has been sent to your email.")
    print("  Open the Google Sheet -> 'Start Number' tab")
    print("  Paste the OTP code into cell B2")
    print("  (The script will read it automatically)")
    print("-" * 55)
    print("")

    otp_code = None
    max_wait = 3600   # 1 hour
    elapsed  = 0
    interval = 30

    while elapsed < max_wait:
        sb.sleep(interval)
        elapsed += interval
        print(f"   Waiting for OTP in Sheet B2... ({elapsed}s / {max_wait}s)")
        try:
            code = sheets_handler.get_otp_from_sheet()
            if code:
                otp_code = str(code).strip()
                print(f"   OTP received from Google Sheet: {otp_code}")
                sheets_handler.clear_otp_from_sheet()
                break
        except Exception as e:
            print(f"   Sheet poll error: {e}")

    if not otp_code:
        raise Exception("OTP timeout: no code found in Google Sheet cell B2 after 1 hour")

    # Step 4: Wait for Verify Authentication page
    print("   Waiting for Verify Authentication page...")
    for _ in range(15):
        sb.sleep(1)
        try:
            body_text = sb.cdp.get_text("body")
            if "Verify Authentication" in body_text or "Passcode" in body_text:
                print("   Verify Authentication page loaded")
                break
        except Exception:
            pass
    else:
        print("   WARNING: Verify Auth page may not have loaded, trying anyway...")

    sb.sleep(1)
    print(f"   Entering OTP: {otp_code}")

    # Fill Passcode — Method 1: named selectors
    filled = False
    for sel in [
        "input[name*='passcode']",
        "input[id*='passcode']",
        "input[name*='Passcode']",
        "input[id*='Passcode']",
        "input[name*='otp']",
        "input[name*='code']",
        "input[placeholder*='asscode']",
    ]:
        try:
            sb.cdp.click(sel)
            sb.sleep(0.2)
            sb.cdp.evaluate(f"document.querySelector('{sel}').value = ''")
            sb.cdp.type(sel, otp_code)
            print(f"   OTP filled via selector: {sel}")
            filled = True
            break
        except Exception:
            continue

    # Fill Passcode — Method 2: JS first visible input
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
            print("   OTP filled via JS (first visible input)")
            filled = True
        except Exception as e:
            print(f"   JS fill failed: {e}")

    if not filled:
        print("   WARNING: Could not find Passcode field — OTP not entered")
        return

    sb.sleep(0.5)

    # Submit
    for btn_sel in [
        "button:contains('Submit')",
        "button[type='submit']",
        "input[type='submit']",
    ]:
        try:
            sb.cdp.click(btn_sel)
            print(f"   OTP submitted via: {btn_sel}")
            break
        except Exception:
            continue

    sb.sleep(4)
    print("   OTP flow complete")


# -------------------------------------------------------------------
# LOGIN VIA BROWSER — returns cookie dict
# -------------------------------------------------------------------

def _login_via_browser() -> dict:
    """
    Opens browser, logs in with the single configured account,
    handles OTP if needed, navigates to search page to confirm session,
    then extracts and saves cookies.
    Returns cookie dict (empty dict on failure).
    """
    cookie_dict = {}
    user_agent  = None
    username    = USERNAME
    password    = PASSWORD_B64

    with SB(uc=True, test=False, locale="en", headless=True) as sb:
        print(f"Opening browser for login (account: {username})...")
        sb.activate_cdp_mode(BASE_URL + "/ui/home")
        sb.sleep(4)

        # Click Sign In
        print("   Clicking Sign In button...")
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

        # Fill User ID
        print(f"   Filling User ID: {username}")
        for sel in [
            "input[placeholder='User ID']",
            "input[name='username']",
            "input[type='text']",
        ]:
            try:
                sb.cdp.click(sel)
                sb.sleep(0.3)
                sb.cdp.type(sel, username)
                print("   User ID filled")
                break
            except Exception:
                continue

        sb.sleep(0.5)

        # Fill Password
        print("   Filling Password...")
        for sel in [
            "input[placeholder='Password']",
            "input[name='password']",
            "input[type='password']",
        ]:
            try:
                sb.cdp.click(sel)
                sb.sleep(0.3)
                sb.cdp.type(sel, password)
                print("   Password filled")
                break
            except Exception:
                continue

        sb.sleep(0.5)

        # Submit via Enter key
        submitted = False
        for sel in [
            "input[placeholder='Password']",
            "input[name='password']",
            "input[type='password']",
        ]:
            try:
                sb.cdp.click(sel)
                sb.sleep(0.2)
                sb.cdp.press_keys(sel, "\n")
                print("   Submitted via Enter key")
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
                    print("   Submitted via Sign In button")
                    break
                except Exception:
                    continue

        sb.sleep(6)

        # Handle OTP if triggered
        url = sb.cdp.get_current_url()
        print(f"   URL after login: {url}")
        if "otp" in url.lower():
            _handle_otp(sb)

        # Verify login succeeded
        try:
            body = sb.cdp.get_text("body")
            if "User ID" in body and "Password" in body and "Sign In" in body[:500]:
                print("   Still on login page — credentials may be wrong")
                return {}
            print("   Login successful!")
        except Exception:
            pass

        # Navigate to search page to confirm session
        print("   Navigating to search page to confirm session...")
        sb.cdp.open(SEARCH_PAGE_URL)
        sb.sleep(5)

        current_url = sb.cdp.get_current_url()
        print(f"   Current URL: {current_url}")
        if "search" not in current_url.lower():
            print("   WARNING: Did not reach search page — login may have failed")
            try:
                print(sb.cdp.get_text("body")[:500])
            except Exception:
                pass
            return {}

        print("   Search page confirmed — extracting cookies...")
        cookie_dict = _extract_cookies_from_browser(sb)

        try:
            user_agent = sb.cdp.get_user_agent()
        except Exception:
            pass

    if cookie_dict:
        save_cookies({"cookies": cookie_dict, "user_agent": user_agent})

    return cookie_dict


# -------------------------------------------------------------------
# GET VALID API SESSION (reuse cookies or fresh login)
# -------------------------------------------------------------------

def get_valid_session() -> requests.Session:
    """
    Returns a valid authenticated requests.Session.
    Reuses saved cookies if still valid, otherwise re-logs in.
    """
    saved = load_cookies()
    if saved:
        cookie_dict = saved.get("cookies", {})
        user_agent  = saved.get("user_agent")
        if cookie_dict:
            api_session = _build_api_session(cookie_dict, user_agent)
            print(f"   Testing saved session for {USERNAME}...")
            if _test_session(api_session):
                return api_session
            else:
                print(f"   Saved session expired — re-logging in")
                delete_cookies()

    print(f"\nLogging in as: {USERNAME}")
    cookie_dict = _login_via_browser()

    if not cookie_dict:
        raise Exception(f"Login failed for {USERNAME}")

    saved = load_cookies()
    ua    = saved.get("user_agent") if saved else None
    return _build_api_session(cookie_dict, ua)


# -------------------------------------------------------------------
# CAPTCHA — solve via 2Captcha
# -------------------------------------------------------------------

def solve_recaptcha(page_url: str) -> str:
    """Submit reCAPTCHA v2 to 2Captcha and return the token."""
    if not CAPTCHA_API_KEY:
        raise Exception(
            "CAPTCHA_API_KEY missing in .env\n"
            "Sign up at 2captcha.com, add $3 credit, paste key in .env"
        )

    print("   Submitting CAPTCHA to 2Captcha...")
    resp = requests.post("http://2captcha.com/in.php", data={
        "key":       CAPTCHA_API_KEY,
        "method":    "userrecaptcha",
        "googlekey": CAPTCHA_SITE_KEY,
        "pageurl":   page_url,
        "json":      1,
    }, timeout=30)

    r = resp.json()
    if r.get("status") != 1:
        raise Exception(f"2Captcha submit error: {r}")

    task_id = r["request"]
    print(f"   Task {task_id} — waiting for solution...")

    for attempt in range(24):  # max 4 minutes
        time.sleep(12)
        poll = requests.get("http://2captcha.com/res.php", params={
            "key":    CAPTCHA_API_KEY,
            "action": "get",
            "id":     task_id,
            "json":   1,
        }, timeout=30)
        r = poll.json()

        if r.get("status") == 1:
            token = r["request"]
            print(f"   CAPTCHA token received (length: {len(token)})")
            print(f"   Token preview: {token[:30]}...")
            return token
        elif r.get("request") == "CAPCHA_NOT_READY":
            print(f"   Not ready... ({(attempt+1)*12}s)")
        else:
            raise Exception(f"2Captcha poll error: {r}")

    raise Exception("2Captcha timeout after 4 minutes")


# -------------------------------------------------------------------
# SEARCH ONE REPORT VIA API
# -------------------------------------------------------------------

def _search_via_api(api_session: requests.Session,
                    report_number: str,
                    captcha_token: str) -> dict:
    """
    POST to the search API with captcha token and report number.
    Returns record dict if found, None if not found.
    Raises Exception("SESSION_EXPIRED") if 401/403.
    Raises Exception("SEARCH_LIMIT_REACHED") on rate limit.
    """
    payload = {
        "fields": {
            "state":             STATE,
            "jurisdiction":      JURISDICTION,
            "firstName":         "",
            "lastName":          "",
            "dateOfLoss":        "",
            "accidentLocation1": "",
            "accidentLocation2": "",
            "reportNumber":      report_number,
        },
        "captchaToken": captcha_token,
        "page": 1,
    }

    print(f"\n   [DEBUG] POST {SEARCH_API_URL}")
    print(f"   [DEBUG] Report number  : {report_number}")
    print(f"   [DEBUG] Token length   : {len(captcha_token)}")
    print(f"   [DEBUG] Token preview  : {captcha_token[:40]}...")
    print(f"   [DEBUG] x-xsrf-token  : {api_session.headers.get('x-xsrf-token', 'MISSING')[:30]}...")
    print(f"   [DEBUG] Cookies present: {list(api_session.cookies.keys())}")

    resp = api_session.post(SEARCH_API_URL, json=payload, timeout=30)

    print(f"   [DEBUG] HTTP {resp.status_code}")
    print(f"   [DEBUG] Full response  : {resp.text[:400]}")

    if resp.status_code == 200:
        data = resp.json()
        code = data.get("code", "")

        if code == "SEARCH_LIMIT_REACHED":
            print("   [LIMIT] Site search limit reached for this session.")
            raise Exception("SEARCH_LIMIT_REACHED")

        if code == "VALIDATION_ERROR":
            msgs = data.get("validationMessages", [])
            print(f"   [DEBUG] Validation errors: {msgs}")
            for m in msgs:
                if m.get("fieldName") == "captchaToken":
                    print("   [DEBUG] CAPTCHA TOKEN REJECTED by server")
            return None

        if code == "OK":
            records = data.get("data", {}).get("records", [])
            print(f"   [DEBUG] Records returned: {len(records)}")

            # Pick the last record group that has actual data (reportNumber not None)
            real_record = None
            for group in reversed(records):
                if group and len(group) > 0:
                    candidate = group[0]
                    if candidate.get("reportNumber") is not None:
                        real_record = candidate
                        break

            if real_record:
                print(f"   [DEBUG] Raw record keys: {list(real_record.keys())}")
                real_record["reportTypeLabel"] = get_report_type_label(
                    real_record.get("reportType") or "U"
                )
                return real_record

            print("   [DEBUG] OK response but 0 usable records — report not found")
            return None

        print(f"   [DEBUG] Unexpected response code: {code}")
        return None

    elif resp.status_code in (401, 403):
        print(f"   [DEBUG] Session expired (HTTP {resp.status_code})")
        raise Exception("SESSION_EXPIRED")

    else:
        print(f"   [DEBUG] Unexpected HTTP {resp.status_code}: {resp.text[:200]}")
        return None


# -------------------------------------------------------------------
# INTER-SEARCH RANDOM DELAY (slower, human-like)
# -------------------------------------------------------------------

def _random_search_delay():
    """
    Wait a random amount between 15–35 seconds between each search.
    Mimics slower, human-like browsing to reduce rate-limit pressure.
    """
    delay = random.uniform(15, 35)
    print(f"   [DELAY] Waiting {delay:.1f}s before next search...")
    time.sleep(delay)


# -------------------------------------------------------------------
# BETWEEN-BATCH PAUSE — 20 minutes, with countdown
# -------------------------------------------------------------------

def _batch_pause(batch_num: int):
    """
    Pause 20 minutes between batches.
    Prints a countdown every 30 seconds.
    """
    wait_sec = 20 * 60   # 20 minutes
    print(f"\n{'='*60}")
    print(f"  [BATCH PAUSE] Batch {batch_num} complete.")
    print(f"  Pausing 20 minutes before next batch...")
    print(f"{'='*60}")
    for remaining in range(wait_sec, 0, -30):
        mins, secs = divmod(remaining, 60)
        print(f"   [BATCH PAUSE] Resuming in {mins}m {secs:02d}s...  ", end="\r")
        time.sleep(30)
    print()
    print("   [BATCH PAUSE] Resuming now.\n")


# -------------------------------------------------------------------
# RATE-LIMIT PAUSE — 10 minutes, infinite retries
# -------------------------------------------------------------------

def _limit_pause(hit_count: int, api_session: requests.Session) -> requests.Session:
    """
    On SEARCH_LIMIT_REACHED: pause 10 minutes, refresh session, return new session.
    Called every time a limit is hit — no maximum, never terminates.
    """
    wait_sec = 10 * 60   # 10 minutes
    print(f"\n   [LIMIT] Rate limit hit #{hit_count}. Pausing 10 minutes...")
    for remaining in range(wait_sec, 0, -30):
        mins, secs = divmod(remaining, 60)
        print(f"   [LIMIT] Resuming in {mins}m {secs:02d}s...  ", end="\r")
        time.sleep(30)
    print()
    print("   [LIMIT] Refreshing session after rate-limit pause...")
    delete_cookies()
    new_session = get_valid_session()
    print("   [LIMIT] Session refreshed. Retrying...\n")
    return new_session


# ===================================================================
# MAIN ENTRY POINT
# ===================================================================

def run_search_session(report_numbers: list,
                       found_callback,
                       not_found_callback,
                       found_so_far: int = 0,
                       target: int = 100,
                       error_callback=None,
                       # Legacy params kept for signature compatibility — ignored
                       account: dict = None,
                       account_idx: int = 0,
                       on_limit_hit=None,
                       no_login: bool = False) -> int:
    """
    Search a list of report numbers using a single logged-in account.

    Behaviour:
    - Login once; reuse session until it expires (then auto-relogin).
    - 15–35s random delay between each individual report search.
    - On SEARCH_LIMIT_REACHED: pause 10 min → refresh session → retry
      the same report — indefinitely, until it succeeds.
    - 3 retries on generic errors before calling error_callback.
    - Batch pausing (20 min) is handled by main.py between batches.
    """
    MAX_RETRIES  = 3
    found_count  = 0
    limit_hits   = 0

    print(f"\n[SESSION] Logging in as: {USERNAME}")
    api_session = get_valid_session()

    for report_num in report_numbers:

        # Global target check
        if found_so_far + found_count >= target:
            print(f"\n*** TARGET REACHED ({target} found) — stopping batch early ***")
            break

        report_str = str(report_num)
        print(f"\n{'='*52}")
        print(f"  Checking report: {report_str}")
        print(f"{'='*52}")

        # Per-report retry loop — keeps going on limit hits
        while True:
            last_error = None
            success    = False

            for attempt in range(1, MAX_RETRIES + 1):
                if attempt > 1:
                    print(f"   [RETRY] Attempt {attempt}/{MAX_RETRIES} for {report_str}...")
                    time.sleep(5)

                try:
                    token  = solve_recaptcha(SEARCH_PAGE_URL)
                    result = _search_via_api(api_session, report_str, token)

                    if result is not None:
                        found_count += 1
                        found_callback(result)
                        print(f"   Found in this batch: {found_count}  |  "
                              f"Global total: {found_so_far + found_count}/{target}")
                        if found_so_far + found_count >= target:
                            print(f"\n*** GLOBAL TARGET {target} REACHED ***")
                            return found_count
                    else:
                        not_found_callback(report_str)

                    success = True
                    break

                except Exception as e:
                    err        = str(e)
                    last_error = err

                    # ── RATE LIMIT: pause 10 min, refresh, retry forever ──
                    if "SEARCH_LIMIT_REACHED" in err:
                        limit_hits  += 1
                        api_session  = _limit_pause(limit_hits, api_session)
                        # Break the attempt loop → outer while True retries
                        # the same report_str from scratch
                        break

                    # ── SESSION EXPIRED: re-login, retry ──
                    if "SESSION_EXPIRED" in err:
                        print("   [SESSION] Session expired — re-logging in...")
                        delete_cookies()
                        api_session = get_valid_session()
                        break   # retry this report

                    # ── Fatal errors: propagate immediately ──
                    if "CAPTCHA_API_KEY" in err:
                        print(f"\n[FATAL] {e}")
                        raise

                    # ── Generic retriable error ──
                    print(f"   [ERROR] Attempt {attempt}/{MAX_RETRIES} failed: {err[:120]}")
                    success = False

            else:
                # Attempt loop finished without a break (all 3 failed generically)
                if not success:
                    print(f"   [ERROR] All {MAX_RETRIES} attempts failed for {report_str}")
                    if error_callback:
                        error_callback(report_str, last_error or "Unknown error")
                    else:
                        not_found_callback(report_str)
                    break  # move to next report

            # If success or all generic retries exhausted → move on
            if success or (last_error and
                           "SEARCH_LIMIT_REACHED" not in last_error and
                           "SESSION_EXPIRED"      not in last_error):
                break
            # Otherwise the while True continues (limit/session retry)

        # Random inter-search delay (only if more reports remain)
        if report_num != report_numbers[-1]:
            _random_search_delay()

    return found_count