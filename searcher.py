"""
searcher.py
-----------
Handles browser login, session management, captcha, and per-report search.

Slot model:
  Slot 0,1,2  — logged-in accounts loaded from Config sheet at runtime
  Slot 3      — no-login (direct URL)

run_slot_batch returns (found_count, next_report, status)
  next_report = exact report to resume from (mid-batch aware)
  status      = "ok" | "limit" | "session" | "consecutive_errors" | "control:<cmd>"
"""
import os
import re
import time
import random
import pickle
import requests
from seleniumbase import SB
from config import (
    NO_LOGIN_SLOT,
    BASE_URL, SEARCH_PAGE_URL, SEARCH_API_URL,
    STATE, JURISDICTION,
    get_report_type_label,
    CAPTCHA_API_KEY, CAPTCHA_SITE_KEY,
    SEARCH_DELAY_MIN, SEARCH_DELAY_MAX,
    CONSECUTIVE_ERROR_LIMIT,
    RESTART_PAUSE_SEC,
)

# -------------------------------------------------------------------
# LIVE SITE KEY
# -------------------------------------------------------------------
_live_site_key: str = None


def _is_valid_recaptcha_key(key: str) -> bool:
    if not key:
        return False
    key = str(key).strip()
    return (
        len(key) == 40
        and key.startswith("6L")
        and bool(re.fullmatch(r'[A-Za-z0-9_-]{40}', key))
    )


def _extract_site_key_from_browser(sb) -> str:
    # Method 1: k= param in reCAPTCHA iframe src
    try:
        key = sb.cdp.evaluate("""
            (function() {
                var frames = document.querySelectorAll(
                    'iframe[src*="recaptcha"], iframe[src*="captcha"]'
                );
                for (var i = 0; i < frames.length; i++) {
                    var m = (frames[i].src||'').match(/[?&]k=([A-Za-z0-9_-]{40})/);
                    if (m) return m[1];
                }
                return null;
            })()
        """)
        if _is_valid_recaptcha_key(key):
            return str(key).strip()
    except Exception:
        pass

    # Method 2: data-sitekey attribute
    try:
        key = sb.cdp.evaluate("""
            (function() {
                var el = document.querySelector('[data-sitekey]');
                return el ? el.getAttribute('data-sitekey') : null;
            })()
        """)
        if _is_valid_recaptcha_key(key):
            return str(key).strip()
    except Exception:
        pass

    # Method 3: tightened patterns in page source
    try:
        html = sb.cdp.get_page_source()
        for pattern in [
            r'[?&]k=(6L[A-Za-z0-9_-]{38})',
            r'"sitekey"\s*:\s*"(6L[A-Za-z0-9_-]{38})"',
            r'sitekey["\s:=]+(6L[A-Za-z0-9_-]{38})',
        ]:
            m = re.search(pattern, html)
            if m and _is_valid_recaptcha_key(m.group(1)):
                return m.group(1)
    except Exception:
        pass

    return None


def _refresh_site_key(sb):
    global _live_site_key
    found = _extract_site_key_from_browser(sb)
    if found:
        if found != _live_site_key:
            print(f"   [CAPTCHA] Site key updated: {found[:20]}...")
        _live_site_key = found
    else:
        print("   [CAPTCHA] Could not extract live site key — using config fallback")


def get_active_site_key() -> str:
    return _live_site_key or CAPTCHA_SITE_KEY


# -------------------------------------------------------------------
# COOKIE PERSISTENCE
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
        resp = api_session.get(f"{BASE_URL}/gateway/nossop/session/user", timeout=10)
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
# BUILD requests.Session
# -------------------------------------------------------------------

def _build_api_session(cookie_dict: dict, user_agent: str = None,
                       proxy: str = None) -> requests.Session:
    session = requests.Session()
    for name, value in cookie_dict.items():
        session.cookies.set(name, value, domain="buycrash.lexisnexisrisk.com")

    ua   = user_agent or (
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
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
        print(f"   Session proxy set: {proxy.split('@')[-1] if '@' in proxy else proxy}")
    if xsrf:
        print(f"   API session built — XSRF: {xsrf[:20]}...")
    else:
        print("   WARNING: XSRF-TOKEN missing")
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

def _handle_otp(sb, slot_idx: int, account_label: str,
                otp_timeout_min: int, mailtm_token: str = None) -> bool:
    """
    Complete OTP flow automatically via Mail.tm API when token available,
    falls back to manual Sheet B2 polling if not configured.
    Returns True if OTP completed, False if timed out.
    """
    wait_sec = otp_timeout_min * 60

    print("=" * 60)
    print(f"  OTP REQUIRED — Slot {slot_idx} ({account_label})")
    if mailtm_token:
        print(f"  Auto-fetching OTP via Mail.tm API...")
    else:
        print(f"  Paste OTP into Google Sheet B2 within {otp_timeout_min} min")
    print("=" * 60)

    # Click Email radio
    for sel in ["input[type='radio'][value*='mail']", "input[type='radio']:first-of-type"]:
        try:
            sb.cdp.click(sel); break
        except Exception:
            continue
    sb.sleep(1)

    # Snapshot inbox BEFORE clicking Send Code
    seen_ids = set()
    if mailtm_token:
        from mailreader import get_inbox_snapshot
        seen_ids = get_inbox_snapshot(mailtm_token)
        print(f"   [OTP] Inbox snapshot: {len(seen_ids)} existing messages")

    # Click Send Code
    for sel in ["button:contains('Send Code')", "button:contains('Continue')",
                "button[type='submit']"]:
        try:
            sb.cdp.click(sel)
            print("   [OTP] Clicked Send Code"); break
        except Exception:
            continue
    sb.sleep(2)

    otp_code = None

    # Method 1: Mail.tm API (automatic, fast)
    if mailtm_token:
        from mailreader import wait_for_otp
        print(f"   [OTP] Fetching via Mail.tm API (max 2 min)...")
        otp_code = wait_for_otp(
            token         = mailtm_token,
            max_wait_sec  = min(wait_sec, 120),
            poll_interval = 8,
            seen_ids      = seen_ids,
        )
        if otp_code:
            print(f"   [OTP] Auto-received: {otp_code}")
        else:
            print(f"   [OTP] Mail.tm timed out — falling back to Sheet B2")

    # Method 2: fallback — poll Google Sheet B2
    if not otp_code:
        import sheets_handler
        print(f"   [OTP] Polling Sheet B2 (up to {otp_timeout_min} min)...")
        elapsed  = 0
        interval = 30
        while elapsed < wait_sec:
            sb.sleep(interval)
            elapsed += interval
            print(f"   [OTP] Waiting... {elapsed}s / {wait_sec}s")
            try:
                code = sheets_handler.get_otp_from_sheet()
                if code:
                    otp_code = str(code).strip()
                    print(f"   [OTP] Received from Sheet: {otp_code}")
                    sheets_handler.clear_otp_from_sheet()
                    break
            except Exception as e:
                print(f"   [OTP] Sheet poll error: {e}")

    if not otp_code:
        print(f"   [OTP] Timeout — no OTP for slot {slot_idx}")
        return False

    # Wait for passcode page
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
        "input[name*='otp']", "input[name*='code']",
        "input[placeholder*='asscode']",
    ]:
        try:
            sb.cdp.click(sel); sb.sleep(0.2)
            sb.cdp.evaluate(f"document.querySelector('{sel}').value = ''")
            sb.cdp.type(sel, otp_code)
            filled = True; break
        except Exception:
            continue

    if not filled:
        try:
            sb.cdp.evaluate(f"""
                (function() {{
                    var inputs = document.querySelectorAll(
                        'input[type="text"],input[type="password"],input:not([type])'
                    );
                    for (var i=0;i<inputs.length;i++) {{
                        if (inputs[i].offsetParent!==null) {{
                            inputs[i].focus();
                            inputs[i].value='{otp_code}';
                            inputs[i].dispatchEvent(new Event('input',{{bubbles:true}}));
                            inputs[i].dispatchEvent(new Event('change',{{bubbles:true}}));
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
            sb.cdp.click(btn); break
        except Exception:
            continue

    sb.sleep(4)
    print("   [OTP] Submitted successfully")
    return True


# -------------------------------------------------------------------
# PROXY PARSING HELPER
# -------------------------------------------------------------------

def _parse_sb_proxy(proxy: str) -> str:
    """
    SeleniumBase proxy support is unreliable with complex passwords
    (underscores, special chars) that providers like IPRoyal use.

    We intentionally return None here — the browser is only used to
    extract session cookies. The proxy is applied on the requests.Session
    for all actual API calls, which is where the rate limit lives.
    """
    return None


# -------------------------------------------------------------------
# LOGIN VIA BROWSER
# -------------------------------------------------------------------

def _login_via_browser(slot_idx: int, account: dict, otp_timeout_min: int,
                       proxy: str = None, mailtm_token: str = None) -> dict:
    username      = account["username"]
    password      = account["password"]
    account_label = f"Account {slot_idx + 1}: {username}"
    cookie_dict   = {}
    user_agent    = None

    print(f"\n   [SLOT {slot_idx}] Logging in as {username}"
          + (f" via proxy {proxy.split('@')[-1]}" if proxy and "@" in proxy else "")
          + "...")

    sb_proxy = _parse_sb_proxy(proxy)

    with SB(uc=True, test=False, locale="en", headless=True,
            proxy=sb_proxy) as sb:
        sb.activate_cdp_mode(BASE_URL + "/ui/home")
        sb.sleep(4)

        for strategy in [
            lambda: sb.cdp.find_element_by_text("Sign In").click(),
            lambda: sb.cdp.click("button:contains('Sign In')"),
            lambda: sb.cdp.gui_click_element("button:contains('Sign In')"),
        ]:
            try:
                strategy(); print("   Clicked Sign In"); break
            except Exception:
                continue
        sb.sleep(2)

        for sel in ["input[placeholder='User ID']", "input[name='username']", "input[type='text']"]:
            try:
                sb.cdp.click(sel); sb.sleep(0.3); sb.cdp.type(sel, username); break
            except Exception:
                continue
        sb.sleep(0.5)

        for sel in ["input[placeholder='Password']", "input[name='password']", "input[type='password']"]:
            try:
                sb.cdp.click(sel); sb.sleep(0.3); sb.cdp.type(sel, password); break
            except Exception:
                continue
        sb.sleep(0.5)

        submitted = False
        for sel in ["input[placeholder='Password']", "input[name='password']", "input[type='password']"]:
            try:
                sb.cdp.click(sel); sb.sleep(0.2)
                sb.cdp.press_keys(sel, "\n")
                submitted = True; break
            except Exception:
                continue

        if not submitted:
            for strategy in [
                lambda: sb.cdp.find_element_by_text("Sign In").click(),
                lambda: sb.cdp.gui_click_element("button[type='submit']"),
                lambda: sb.cdp.click("button[type='submit']"),
            ]:
                try:
                    strategy(); break
                except Exception:
                    continue
        sb.sleep(6)

        url = sb.cdp.get_current_url()
        print(f"   URL after login: {url}")
        if "otp" in url.lower():
            otp_ok = _handle_otp(sb, slot_idx, account_label,
                                 otp_timeout_min, mailtm_token)
            if not otp_ok:
                raise Exception("OTP_TIMEOUT")

        try:
            body = sb.cdp.get_text("body")
            if "User ID" in body and "Sign In" in body[:500]:
                print(f"   [SLOT {slot_idx}] Still on login page")
                return {}
        except Exception:
            pass

        sb.cdp.open(SEARCH_PAGE_URL)
        sb.sleep(5)
        if "search" not in sb.cdp.get_current_url().lower():
            print(f"   [SLOT {slot_idx}] Did not reach search page")
            return {}

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
# NO-LOGIN SESSION
# -------------------------------------------------------------------

def _get_no_login_session(proxy: str = None) -> requests.Session:
    cookie_dict = {}
    user_agent  = None

    sb_proxy = _parse_sb_proxy(proxy)

    with SB(uc=True, test=False, locale="en", headless=True,
            proxy=sb_proxy) as sb:
        print(f"   [SLOT {NO_LOGIN_SLOT} / NO-LOGIN] Navigating to search page"
              + (f" via {proxy.split('@')[-1]}" if proxy and "@" in proxy else "") + "...")
        sb.activate_cdp_mode(SEARCH_PAGE_URL)
        sb.sleep(5)
        print(f"   URL: {sb.cdp.get_current_url()}")
        _refresh_site_key(sb)
        cookie_dict = _extract_cookies(sb)
        try:
            user_agent = sb.cdp.get_user_agent()
        except Exception:
            pass

    if not cookie_dict:
        raise Exception("NO-LOGIN: Could not obtain cookies")

    return _build_api_session(cookie_dict, user_agent, proxy)


# -------------------------------------------------------------------
# GET SESSION FOR SLOT
# -------------------------------------------------------------------

def get_session_for_slot(slot_idx: int, accounts: list,
                         otp_timeout_min: int,
                         proxy: str = None,
                         mailtm_tokens: list = None) -> requests.Session:
    """
    accounts        : list of {"username":..,"password":..} from Config sheet
    otp_timeout_min : from Config sheet
    proxy           : optional proxy URL
    mailtm_tokens   : list of Mail.tm tokens indexed by slot (slot 0 = index 0)
    """
    if slot_idx == NO_LOGIN_SLOT:
        return _get_no_login_session(proxy)

    if slot_idx >= len(accounts):
        raise Exception(f"LOGIN_FAILED: no account configured for slot {slot_idx}")

    account       = accounts[slot_idx]
    mailtm_token  = (mailtm_tokens[slot_idx]
                     if mailtm_tokens and slot_idx < len(mailtm_tokens)
                     else None) or None

    # When proxy changes, force fresh login (cached cookies are IP-bound)
    saved = _load_cookies(slot_idx)
    if saved:
        cookie_dict      = saved.get("cookies", {})
        ua               = saved.get("user_agent")
        saved_proxy      = saved.get("proxy")
        proxy_unchanged  = (saved_proxy == proxy)
        if cookie_dict and proxy_unchanged:
            api_session = _build_api_session(cookie_dict, ua, proxy)
            if _test_session(api_session, slot_idx):
                return api_session
        print(f"   [SLOT {slot_idx}] Session expired or proxy changed — re-logging in")
        _delete_cookies(slot_idx)

    cookie_dict = _login_via_browser(slot_idx, account, otp_timeout_min,
                                     proxy, mailtm_token)
    if not cookie_dict:
        raise Exception(f"LOGIN_FAILED for slot {slot_idx}")

    saved = _load_cookies(slot_idx)
    ua    = saved.get("user_agent") if saved else None
    # Store proxy alongside cookies so we can detect proxy change next run
    _save_cookies(slot_idx, {"cookies": cookie_dict, "user_agent": ua, "proxy": proxy})
    return _build_api_session(cookie_dict, ua, proxy)


# -------------------------------------------------------------------
# CAPTCHA
# -------------------------------------------------------------------

def solve_recaptcha(page_url: str) -> str:
    if not CAPTCHA_API_KEY:
        raise Exception("CAPTCHA_API_KEY missing in .env")

    site_key = get_active_site_key()
    print(f"   Submitting CAPTCHA (site key: {site_key[:20]}...)")

    resp = requests.post("http://2captcha.com/in.php", data={
        "key":       CAPTCHA_API_KEY,
        "method":    "userrecaptcha",
        "googlekey": site_key,
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
            "key": CAPTCHA_API_KEY, "action": "get", "id": task_id, "json": 1,
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
# SINGLE REPORT SEARCH
# -------------------------------------------------------------------

def _search_via_api(api_session: requests.Session,
                    report_number: str, captcha_token: str) -> dict:
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
            print(f"   [DEBUG] Validation: {data.get('validationMessages', [])}")
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
# RANDOM DELAY
# -------------------------------------------------------------------

def _random_delay():
    delay = random.uniform(SEARCH_DELAY_MIN, SEARCH_DELAY_MAX)
    print(f"   [DELAY] {delay:.1f}s...")
    time.sleep(delay)


# -------------------------------------------------------------------
# RUN BATCH FOR ONE SLOT
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
    Returns (found_count, next_report, status) where status is one of:
      "ok"                    — batch completed normally
      "limit"                 — SEARCH_LIMIT_REACHED
      "session"               — SESSION_EXPIRED mid-batch
      "consecutive_errors"    — 20 back-to-back errors
      "control:stop"          — user typed stop in sheet
      "control:restart"       — user typed restart in sheet
    """
    import sheets_handler

    MAX_RETRIES       = 3
    found_count       = 0
    consecutive_errs  = 0
    slot_label        = f"SLOT {slot_idx}" if slot_idx < NO_LOGIN_SLOT else f"SLOT {NO_LOGIN_SLOT}/NO-LOGIN"
    next_report       = report_numbers[-1] + 1   # default: completed full batch

    for i, report_num in enumerate(report_numbers):

        if found_so_far + found_count >= target:
            print(f"\n*** TARGET REACHED — stopping slot {slot_idx} early ***")
            next_report = report_num
            break

        report_str = str(report_num)
        print(f"\n{'='*52}")
        print(f"  [{slot_label}] Report: {report_str}  ({i+1}/{len(report_numbers)})")
        print(f"{'='*52}")

        # ── Check control cell after every report ──────────────────
        cmd = sheets_handler.check_control()
        if cmd == "stop":
            return found_count, report_num, "control:stop"
        elif cmd == "restart":
            return found_count, report_num, "control:restart"
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
                    found_count      += 1
                    consecutive_errs  = 0   # reset on any success
                    found_callback(result)
                    print(f"   [{slot_label}] Found: {found_count} | "
                          f"Global: {found_so_far + found_count}/{target}")
                    if found_so_far + found_count >= target:
                        print(f"\n*** GLOBAL TARGET {target} REACHED ***")
                        next_report = report_num + 1
                        return found_count, next_report, "ok"
                else:
                    consecutive_errs = 0   # not-found is a clean result
                    not_found_callback(report_str)

                success = True
                break

            except Exception as e:
                err        = str(e)
                last_error = err

                if "SEARCH_LIMIT_REACHED" in err:
                    print(f"   [{slot_label}] SEARCH_LIMIT_REACHED on {report_str} "
                          f"(#{i+1}/{len(report_numbers)})")
                    return found_count, report_num, "limit"

                if "SESSION_EXPIRED" in err:
                    print(f"   [{slot_label}] Session expired on {report_str}")
                    return found_count, report_num, "session"

                if "CAPTCHA_API_KEY" in err:
                    raise

                print(f"   [ERROR] Attempt {attempt}/{MAX_RETRIES}: {err[:120]}")

        if not success:
            consecutive_errs += 1
            print(f"   [ERROR] All retries failed for {report_str} "
                  f"(consecutive: {consecutive_errs}/{CONSECUTIVE_ERROR_LIMIT})")
            if error_callback:
                error_callback(report_str, last_error or "Unknown error")
            else:
                not_found_callback(report_str)

            if consecutive_errs >= CONSECUTIVE_ERROR_LIMIT:
                print(f"\n[FATAL] {CONSECUTIVE_ERROR_LIMIT} consecutive errors — stopping")
                return found_count, report_num, "consecutive_errors"
        else:
            consecutive_errs = 0

        if i < len(report_numbers) - 1:
            _random_delay()

    return found_count, next_report, "ok"