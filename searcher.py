"""
searcher.py
-----------
Strategy:
1. Login ONCE via browser UI — save cookies to file
2. On next run — load cookies from file, skip login if still valid
3. For each report — solve reCAPTCHA via 2Captcha → call API directly
4. Browser stays open entire session (no re-login per batch)
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
# COOKIE PERSISTENCE — save/load so we skip login on next run
# -------------------------------------------------------------------

def save_cookies(cookies: dict):
    """Save cookies to disk for reuse next run."""
    with open(COOKIES_FILE, "wb") as f:
        pickle.dump(cookies, f)
    print(f"   💾 Session cookies saved to {COOKIES_FILE}")


def load_cookies() -> dict:
    """Load cookies from disk if available."""
    if os.path.exists(COOKIES_FILE):
        with open(COOKIES_FILE, "rb") as f:
            cookies = pickle.load(f)
        print(f"   📂 Loaded saved cookies from {COOKIES_FILE}")
        return cookies
    return {}


def delete_cookies():
    """Delete saved cookies (force re-login next run)."""
    if os.path.exists(COOKIES_FILE):
        os.remove(COOKIES_FILE)
        print("   🗑️  Deleted saved cookies")


def _test_session(api_session: requests.Session) -> bool:
    """
    Quick check if our session cookies are still valid
    by calling the user session endpoint.
    """
    try:
        resp = api_session.get(
            f"{BASE_URL}/gateway/nossop/session/user",
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("loginId"):
                print(f"   ✅ Session valid — logged in as: {data.get('loginId')}")
                return True
        print(f"   ⚠️  Session check returned {resp.status_code}")
        return False
    except Exception as e:
        print(f"   ⚠️  Session check error: {e}")
        return False


# -------------------------------------------------------------------
# BUILD requests.Session from cookie dict
# -------------------------------------------------------------------

def _build_api_session_from_dict(cookie_dict: dict,
                                  user_agent: str = None) -> requests.Session:
    api_session = requests.Session()
    for name, value in cookie_dict.items():
        api_session.cookies.set(
            name, value, domain="buycrash.lexisnexisrisk.com"
        )
    ua = user_agent or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    api_session.headers.update({
        "User-Agent": ua,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Referer": SEARCH_PAGE_URL,
        "Origin": BASE_URL,
    })
    return api_session


# -------------------------------------------------------------------
# EXTRACT COOKIES from browser into a plain dict
# -------------------------------------------------------------------

def _extract_cookies_from_browser(sb) -> dict:
    """Pull cookies from SeleniumBase browser into a plain dict."""
    cookie_dict = {}
    try:
        raw = sb.cdp.get_all_cookies()
        for c in raw:
            try:
                # Handle both object-style and dict-style cookies
                name  = c.name  if hasattr(c, "name")  else c.get("name", "")
                value = c.value if hasattr(c, "value") else c.get("value", "")
                if name and value:
                    cookie_dict[name] = value
            except Exception:
                pass
        print(f"   🍪 Extracted {len(cookie_dict)} cookies from browser")
    except Exception as e:
        print(f"   ⚠️  Cookie extraction error: {e}")
    return cookie_dict


# -------------------------------------------------------------------
# LOGIN via browser UI — only called when no valid session exists
# -------------------------------------------------------------------

def _login_via_browser() -> dict:
    """
    Opens browser, logs in, extracts and returns cookie dict.
    Browser is opened and closed just for login.
    """
    cookie_dict = {}
    user_agent  = None

    with SB(uc=True, test=False, locale="en", headless=False) as sb:
        print(f"🔐 Opening browser for login...")
        sb.activate_cdp_mode(BASE_URL + "/ui/home")
        sb.sleep(4)

        # ── Click Sign In button ──────────────────────────────────
        print("   Clicking Sign In button...")
        clicked = False

        # Try multiple strategies
        strategies = [
            lambda: sb.cdp.find_element_by_text("Sign In").click(),
            lambda: sb.cdp.click("button:contains('Sign In')"),
            lambda: sb.cdp.gui_click_element("button:contains('Sign In')"),
        ]
        for strategy in strategies:
            try:
                strategy()
                clicked = True
                print("   ✅ Clicked Sign In")
                break
            except Exception:
                continue

        if not clicked:
            print("   ⚠️  Could not click Sign In button")

        sb.sleep(2)

        # ── Fill User ID ──────────────────────────────────────────
        print(f"   Filling User ID: {USERNAME}")
        for sel in ["input[placeholder='User ID']",
                    "input[name='username']",
                    "input[type='text']"]:
            try:
                sb.cdp.click(sel)
                sb.sleep(0.3)
                sb.cdp.type(sel, USERNAME)
                print(f"   ✅ Filled User ID")
                break
            except Exception:
                continue

        sb.sleep(0.5)

        # ── Fill Password ─────────────────────────────────────────
        print("   Filling Password...")
        for sel in ["input[placeholder='Password']",
                    "input[name='password']",
                    "input[type='password']"]:
            try:
                sb.cdp.click(sel)
                sb.sleep(0.3)
                sb.cdp.type(sel, get_password())
                print(f"   ✅ Filled Password")
                break
            except Exception:
                continue

        sb.sleep(0.5)

                # ── Submit Login ───────────────────────────────────────
        print("   Submitting login...")
        submitted = False

        # Method 1: Press Enter on password field
        try:
            for sel in ["input[placeholder='Password']",
                        "input[name='password']",
                        "input[type='password']"]:

                try:
                    sb.cdp.click(sel)
                    sb.sleep(0.2)
                    sb.cdp.press_keys(sel, "\n")
                    submitted = True
                    print("   ✅ Submitted via Enter key")
                    break
                except Exception:
                    continue
        except Exception:
            pass

        # Method 2: Click Sign In button
        if not submitted:
            try:
                for btn in [
                    "button[type='submit']",
                    "button:contains('Sign In')",
                    "input[type='submit']"
                ]:
                    try:
                        sb.cdp.gui_click_element(btn)
                        submitted = True
                        print(f"   ✅ Clicked Sign In button using: {btn}")
                        break
                    except Exception:
                        continue
            except Exception as e:
                print(f"   ⚠️ Submit failed: {e}")

        print("   ⏳ Waiting for login to complete...")

        sb.sleep(6)

        # ── Verify login ──────────────────────────────────────────
        try:
            url  = sb.cdp.get_current_url()
            body = sb.cdp.get_text("body")
            print(f"   📍 URL after submit: {url}")

            # If still showing login form, login failed
            if "User ID" in body and "Password" in body and "Sign In" in body[:500]:
                print("   ❌ Still on login page — credentials may be wrong")
                print("      Check SITE_USERNAME and PASSWORD_B64 in .env")
                return {}
            else:
                print("   ✅ Login successful!")
        except Exception:
            pass

                # ── Navigate to search page after login ───────────────
        print("   🌐 Opening search page...")

        sb.cdp.open(SEARCH_PAGE_URL)
        sb.sleep(5)

        current_url = sb.cdp.get_current_url()
        print(f"   📍 Current URL: {current_url}")

        # Verify we actually reached search page
        if "search" not in current_url.lower():
            print("   ❌ Login failed or redirected back to home page")
            print("      Browser did not reach search page")

            try:
                body = sb.cdp.get_text("body")[:1000]
                print(body)
            except Exception:
                pass

            return {}

        print("   ✅ Search page loaded successfully")

        # ── Extract cookies and user agent ────────────────────────
        cookie_dict = _extract_cookies_from_browser(sb)
        try:
            user_agent = sb.cdp.get_user_agent()
        except Exception:
            pass

    # Save cookies for reuse
    if cookie_dict:
        save_cookies({"cookies": cookie_dict, "user_agent": user_agent})

    return cookie_dict


# -------------------------------------------------------------------
# GET VALID API SESSION (login or reuse saved cookies)
# -------------------------------------------------------------------

def get_valid_session() -> requests.Session:
    """
    Returns a valid authenticated requests.Session.
    Uses saved cookies if still valid, otherwise re-logs in.
    """
    # Try loading saved cookies first
    saved = load_cookies()
    if saved:
        cookie_dict = saved.get("cookies", {})
        user_agent  = saved.get("user_agent")
        if cookie_dict:
            api_session = _build_api_session_from_dict(cookie_dict, user_agent)
            print("   🔄 Testing saved session...")
            if _test_session(api_session):
                return api_session
            else:
                print("   ⚠️  Saved session expired — need to re-login")
                delete_cookies()

    # No valid saved session — do fresh login
    print("\n🔑 No valid session found — performing fresh login...")
    cookie_dict = _login_via_browser()

    if not cookie_dict:
        raise Exception("Login failed — could not obtain session cookies")

    saved = load_cookies()
    ua = saved.get("user_agent") if saved else None
    return _build_api_session_from_dict(cookie_dict, ua)


# -------------------------------------------------------------------
# CAPTCHA SOLVING via 2Captcha
# -------------------------------------------------------------------

def solve_recaptcha_v2(page_url: str) -> str:
    """Submit reCAPTCHA v2 to 2Captcha and return the token."""

    if not CAPTCHA_API_KEY:
        raise Exception(
            "CAPTCHA_API_KEY not set in .env — "
            "sign up at 2captcha.com and add your key"
        )

    print("   🤖 Submitting CAPTCHA to 2Captcha...")

    resp = requests.post("http://2captcha.com/in.php", data={
        "key":       CAPTCHA_API_KEY,
        "method":    "userrecaptcha",
        "googlekey": CAPTCHA_SITE_KEY,
        "pageurl":   page_url,
        "json":      1,
    }, timeout=30)

    result = resp.json()
    if result.get("status") != 1:
        raise Exception(f"2Captcha submit failed: {result}")

    task_id = result["request"]
    print(f"   ⏳ Task {task_id} submitted — waiting for solution...")

    for attempt in range(24):   # max 2 minutes
        time.sleep(5)
        poll = requests.get("http://2captcha.com/res.php", params={
            "key":    CAPTCHA_API_KEY,
            "action": "get",
            "id":     task_id,
            "json":   1,
        }, timeout=30)

        r = poll.json()
        if r.get("status") == 1:
            token = r["request"]
            print(f"   ✅ CAPTCHA solved! Token length: {len(token)}")
            return token
        elif r.get("request") == "CAPCHA_NOT_READY":
            print(f"   ⏳ ({attempt+1}/24) not ready yet...")
        else:
            raise Exception(f"2Captcha error: {r}")

    raise Exception("2Captcha timeout after 2 minutes")


# -------------------------------------------------------------------
# SEARCH via API
# -------------------------------------------------------------------

def _search_via_api(api_session: requests.Session,
                    report_number: str,
                    captcha_token: str):
    """Call search API and return record dict or None."""
    payload = {
        "fields": {
            "state":            STATE,
            "jurisdiction":     JURISDICTION,
            "firstName":        "",
            "lastName":         "",
            "dateOfLoss":       "",
            "accidentLocation1":"",
            "accidentLocation2":"",
            "reportNumber":     report_number,
        },
        "captchaToken": captcha_token,
        "page": 1,
    }

    resp = api_session.post(SEARCH_API_URL, json=payload, timeout=30)

    if resp.status_code == 200:
        data    = resp.json()
        records = data.get("data", {}).get("records", [])
        if records and len(records[0]) > 0:
            record = records[0][0]
            record["reportTypeLabel"] = get_report_type_label(
                record.get("reportType", "U")
            )
            return record
        return None

    elif resp.status_code in (401, 403):
        raise Exception("SESSION_EXPIRED")
    else:
        print(f"   ⚠️  API HTTP {resp.status_code}: {resp.text[:150]}")
        return None


# -------------------------------------------------------------------
# MAIN ENTRY POINT
# -------------------------------------------------------------------

def run_search_session(report_numbers: list,
                       found_callback,
                       not_found_callback) -> int:
    """
    Get/reuse valid session, then search each report number via API.
    Login only happens when no valid session exists.
    """
    found_count = 0

    # Get session — reuses saved cookies or logs in fresh
    api_session = get_valid_session()

    for report_num in report_numbers:
        report_str = str(report_num)
        print(f"\n🔍 Checking report: {report_str}")

        try:
            # Get fresh captcha token for this request
            token = solve_recaptcha_v2(SEARCH_PAGE_URL)

            result = _search_via_api(api_session, report_str, token)

            if result is not None:
                found_count += 1
                found_callback(result)
                print(f"   🎉 Found {found_count} valid report(s) so far")
            else:
                not_found_callback(report_str)

        except Exception as e:
            if "SESSION_EXPIRED" in str(e):
                print("   ⚠️  Session expired — deleting cookies, will re-login next batch")
                delete_cookies()
                raise  # Let main.py restart the batch with fresh login
            elif "CAPTCHA_API_KEY not set" in str(e):
                print(f"\n❌ {e}")
                raise
            else:
                print(f"   ⚠️  Error on {report_str}: {e}")
                not_found_callback(report_str)

        time.sleep(1)

    return found_count