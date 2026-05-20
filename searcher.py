"""
searcher.py
-----------
Architecture (restored to working API-based approach):
  1. Login ONCE via browser UI  ->  extract session cookies
  2. Build a requests.Session with those cookies + correct headers
  3. For each report: solve captcha via 2Captcha -> POST to API directly
  4. Parse clean JSON response (no page scraping needed)
  5. Save cookies to disk so next run skips login if session still alive

OTP (when site detects unrecognised location):
  - Handled in the browser during login
  - User pastes OTP into Google Sheet Start Number!B2
  - Script polls that cell automatically
"""
import os
import time
import json
import pickle
import requests
from seleniumbase import SB
from config import (
    USERNAME, get_password,
    BASE_URL, SEARCH_PAGE_URL, SEARCH_API_URL,
    STATE, JURISDICTION,
    get_report_type_label,
    CAPTCHA_API_KEY, CAPTCHA_SITE_KEY,
)

COOKIES_FILE = "session_cookies.pkl"


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
        print("   Deleted saved cookies (will re-login next run)")


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
    IMPORTANT: also sets x-xsrf-token header from the XSRF-TOKEN cookie
               (required by the site's CSRF protection on every POST).
    """
    session = requests.Session()

    for name, value in cookie_dict.items():
        session.cookies.set(name, value, domain="buycrash.lexisnexisrisk.com")

    ua = user_agent or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    )

    # x-xsrf-token MUST match the XSRF-TOKEN cookie — required by the API
    xsrf = cookie_dict.get("XSRF-TOKEN", "")

    session.headers.update({
        "User-Agent":       ua,
        "Content-Type":     "application/json",
        "Accept":           "application/json, text/plain, */*",
        "Accept-Language":  "en",
        "Referer":          SEARCH_PAGE_URL,
        "Origin":           BASE_URL,
        "lnbc-client-version": "1.0.145",
        "x-xsrf-token":    xsrf,        # <-- CSRF header the API requires
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
    max_wait  = 288   # 4 minutes
    elapsed   = 0
    interval  = 12

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
        raise Exception("OTP timeout: no code found in Google Sheet cell B2 after 4 minutes")

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
    Opens browser, logs in, handles OTP if needed,
    navigates to search page to confirm session, then extracts cookies.
    Returns cookie dict (empty dict on failure).
    """
    cookie_dict = {}
    user_agent  = None

    with SB(uc=True, test=False, locale="en", headless=False) as sb:
        print("Opening browser for login...")
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
        print(f"   Filling User ID: {USERNAME}")
        for sel in [
            "input[placeholder='User ID']",
            "input[name='username']",
            "input[type='text']",
        ]:
            try:
                sb.cdp.click(sel)
                sb.sleep(0.3)
                sb.cdp.type(sel, USERNAME)
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
                sb.cdp.type(sel, get_password())
                print("   Password filled")
                break
            except Exception:
                continue

        sb.sleep(0.5)

        # Submit
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

        # Navigate to search page to confirm session and pick up any additional cookies
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
            print("   Testing saved session...")
            if _test_session(api_session):
                return api_session
            else:
                print("   Saved session expired — need to re-login")
                delete_cookies()

    print("\nNo valid session — performing fresh browser login...")
    cookie_dict = _login_via_browser()

    if not cookie_dict:
        raise Exception("Login failed — could not obtain session cookies")

    saved      = load_cookies()
    ua         = saved.get("user_agent") if saved else None
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
# SEARCH ONE REPORT VIA API — the core function
# -------------------------------------------------------------------

def _search_via_api(api_session: requests.Session,
                    report_number: str,
                    captcha_token: str) -> dict:
    """
    POST to /search-svc/ssrqop/search with captcha token and report number.
    Returns record dict if found, None if not found.
    Raises Exception("SESSION_EXPIRED") if 401/403.
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

    # ── DEBUG: log exactly what we're sending ──────────────────────
    print(f"\n   [DEBUG] POST {SEARCH_API_URL}")
    print(f"   [DEBUG] Report number  : {report_number}")
    print(f"   [DEBUG] Token length   : {len(captcha_token)}")
    print(f"   [DEBUG] Token preview  : {captcha_token[:40]}...")
    print(f"   [DEBUG] x-xsrf-token  : {api_session.headers.get('x-xsrf-token', 'MISSING')[:30]}...")
    print(f"   [DEBUG] Cookies present: {list(api_session.cookies.keys())}")

    solve_time = time.time()

    resp = api_session.post(SEARCH_API_URL, json=payload, timeout=30)

    elapsed = time.time() - solve_time
    print(f"   [DEBUG] Response in {elapsed:.1f}s — HTTP {resp.status_code}")
    print(f"   [DEBUG] Full response  : {resp.text[:400]}")

    if resp.status_code == 200:
        data = resp.json()
        code = data.get("code", "")

        if code == "VALIDATION_ERROR":
            msgs = data.get("validationMessages", [])
            print(f"   [DEBUG] Validation errors: {msgs}")
            # Check specifically for captcha error
            for m in msgs:
                if m.get("fieldName") == "captchaToken":
                    print("   [DEBUG] CAPTCHA TOKEN REJECTED by server")
                    print("          Possible reasons:")
                    print("          1. Token expired (>2 min between solve and use)")
                    print("          2. Wrong captcha type (site may use Enterprise)")
                    print("          3. XSRF-TOKEN mismatch")
                    print("          4. Site key changed")
            return None  # Treat as not found, but log it

        if code == "OK":
            records = data.get("data", {}).get("records", [])
            print(f"   [DEBUG] Records returned: {len(records)}")
            if records and len(records) > 0 and len(records[0]) > 0:
                record = records[0][0]
                print(f"   [DEBUG] Raw record keys: {list(record.keys())}")
                record["reportTypeLabel"] = get_report_type_label(
                    record.get("reportType", "U")
                )
                return record
            print("   [DEBUG] OK response but 0 records — report not found")
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
# MAIN ENTRY POINT
# -------------------------------------------------------------------

def run_search_session(report_numbers: list,
                       found_callback,
                       not_found_callback,
                       found_so_far: int = 0,
                       target: int = 3) -> int:
    """
    Get/reuse a valid API session, then search each report number.
    found_so_far : count of found reports BEFORE this batch.
    target       : stop when found_so_far + found_count >= target.
    Returns count of found reports in THIS batch.
    """
    found_count = 0

    # Get session (reuse cookies or fresh browser login)
    api_session = get_valid_session()

    for report_num in report_numbers:

        # Global stop check
        if found_so_far + found_count >= target:
            print(f"\n*** TARGET REACHED ({target} found) — stopping batch early ***")
            break

        report_str = str(report_num)
        print(f"\n{'='*52}")
        print(f"  Checking report: {report_str}")
        print(f"{'='*52}")

        try:
            token = solve_recaptcha(SEARCH_PAGE_URL)

            result = _search_via_api(api_session, report_str, token)

            if result is not None:
                found_count += 1
                found_callback(result)
                print(f"   Found in this batch: {found_count}  |  "
                      f"Global total: {found_so_far + found_count}/{target}")

                if found_so_far + found_count >= target:
                    print(f"\n*** GLOBAL TARGET {target} REACHED — stopping now ***")
                    break
            else:
                not_found_callback(report_str)

        except Exception as e:
            if "SESSION_EXPIRED" in str(e):
                print("   Session expired — deleting cookies, will re-login next batch")
                delete_cookies()
                raise   # Let main.py restart with fresh login
            elif "CAPTCHA_API_KEY" in str(e):
                print(f"\nFATAL: {e}")
                raise
            else:
                print(f"   Error on {report_str}: {e}")
                not_found_callback(report_str)

        time.sleep(1)

    return found_count