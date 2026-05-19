"""
searcher.py
-----------
Handles login, navigation, CAPTCHA solving, and search
using SeleniumBase CDP Mode for stealth.
"""
import time
import json
import uuid
import requests
from seleniumbase import SB
from config import (
    USERNAME, get_password,
    BASE_URL, LOGIN_URL, SEARCH_PAGE_URL, SEARCH_API_URL,
    STATE, JURISDICTION,
    get_report_type_label,
)


# -------------------------------------------------------------------
# MAIN SESSION
# -------------------------------------------------------------------

def run_search_session(report_numbers: list, found_callback, not_found_callback) -> int:
    """
    Opens browser, logs in via UI, then searches each report number.
    Returns number of found reports.
    """
    found_count = 0

    with SB(uc=True, test=False, locale="en", headless=False) as sb:

        # ── Step 1: Login via UI ──────────────────────────────────
        _login_via_ui(sb)

        # ── Step 2: Go to search page ─────────────────────────────
        print(f"\n🌐 Navigating to search page...")
        sb.cdp.open(SEARCH_PAGE_URL)
        sb.sleep(4)

        # Extract cookies for API calls
        api_session = _build_api_session(sb)

        print(f"📋 Processing {len(report_numbers)} report numbers...")

        # ── Step 3: Loop through report numbers ───────────────────
        for report_num in report_numbers:
            report_str = str(report_num)
            print(f"\n🔍 Checking report number: {report_str}")

            try:
                result = _search_single_report(sb, api_session, report_str)

                if result is not None:
                    found_count += 1
                    found_callback(result)
                    print(f"   ✅ Found {found_count} valid report(s) so far")
                else:
                    not_found_callback(report_str)

            except Exception as e:
                print(f"   ⚠️  Error on report {report_str}: {e}")
                not_found_callback(report_str)
                # Reload search page and continue
                try:
                    sb.cdp.open(SEARCH_PAGE_URL)
                    sb.sleep(4)
                    api_session = _build_api_session(sb)
                except Exception:
                    pass

            time.sleep(2)

    return found_count


# -------------------------------------------------------------------
# LOGIN via UI clicks
# -------------------------------------------------------------------

def _login_via_ui(sb):
    """Click Sign In button, fill credentials, submit."""
    print(f"🔐 Opening home page...")
    sb.activate_cdp_mode(BASE_URL + "/ui/home")
    sb.sleep(4)

    # Click the "Sign In" button/dropdown in the navbar
    print("   Clicking Sign In button...")
    sign_in_selectors = [
        "button.sign-in-btn",
        "a.sign-in",
        "button:contains('Sign In')",
        ".sign-in-button",
        "button[id*='sign']",
        "a[href*='sign']",
        # Generic — visible button with Sign In text
        "button",
    ]

    clicked = False
    for selector in sign_in_selectors:
        try:
            # Try finding by text content first
            if selector == "button":
                # Find all buttons and click the one with Sign In text
                sb.cdp.find_element_by_text("Sign In").click()
                clicked = True
                print(f"   ✅ Clicked Sign In via text search")
                break
            else:
                sb.cdp.click(selector)
                clicked = True
                print(f"   ✅ Clicked Sign In via: {selector}")
                break
        except Exception:
            continue

    if not clicked:
        # Last resort: gui click
        print("   Trying GUI click on Sign In...")
        try:
            sb.cdp.gui_click_element("button")
        except Exception as e:
            print(f"   ⚠️  Could not click Sign In: {e}")

    sb.sleep(2)

    # Fill User ID field
    print(f"   Filling User ID: {USERNAME}")
    user_id_selectors = [
        "input[placeholder='User ID']",
        "input[name='username']",
        "input[id='username']",
        "input[type='text']",
        "input[autocomplete='username']",
    ]
    for selector in user_id_selectors:
        try:
            sb.cdp.type(selector, USERNAME)
            print(f"   ✅ Filled User ID via: {selector}")
            break
        except Exception:
            continue

    sb.sleep(0.5)

    # Fill Password field
    print("   Filling Password...")
    password_selectors = [
        "input[placeholder='Password']",
        "input[name='password']",
        "input[id='password']",
        "input[type='password']",
        "input[autocomplete='current-password']",
    ]
    for selector in password_selectors:
        try:
            sb.cdp.type(selector, get_password())
            print(f"   ✅ Filled Password via: {selector}")
            break
        except Exception:
            continue

    sb.sleep(0.5)

    # Click the Sign In submit button inside the form
    print("   Submitting login form...")
    submit_selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button.btn-primary",
        "button.login-btn",
    ]

    submitted = False
    for selector in submit_selectors:
        try:
            sb.cdp.click(selector)
            submitted = True
            print(f"   ✅ Submitted via: {selector}")
            break
        except Exception:
            continue

    if not submitted:
        # Try clicking by text
        try:
            sb.cdp.find_element_by_text("Sign In", tag_name="button").click()
            submitted = True
            print("   ✅ Submitted via text search")
        except Exception:
            pass

    if not submitted:
        # Press Enter on password field
        try:
            sb.cdp.evaluate(
                "document.querySelector('input[type=\"password\"]').dispatchEvent("
                "new KeyboardEvent('keypress', {key: 'Enter', keyCode: 13, bubbles: true}))"
            )
            print("   ✅ Submitted via Enter key")
        except Exception as e:
            print(f"   ⚠️  Submit failed: {e}")

    print("   ⏳ Waiting for login to complete...")
    sb.sleep(5)

    # Verify login succeeded by checking URL or page content
    try:
        current_url = sb.cdp.get_current_url()
        print(f"   📍 Current URL after login: {current_url}")

        page_text = sb.cdp.get_text("body")
        if "Sign In" in page_text[:100] and "User ID" in page_text:
            print("   ⚠️  Still on login page — login may have failed")
        else:
            print("   ✅ Login appears successful!")
    except Exception:
        pass


# -------------------------------------------------------------------
# BUILD API SESSION from browser cookies
# -------------------------------------------------------------------

def _build_api_session(sb) -> requests.Session:
    """Extract browser cookies into a requests.Session for API calls."""
    api_session = requests.Session()
    try:
        browser_cookies = sb.cdp.get_all_cookies()
        for cookie in browser_cookies:
            api_session.cookies.set(
                cookie.get("name", ""),
                cookie.get("value", ""),
                domain="buycrash.lexisnexisrisk.com",
            )
        print(f"   🍪 {len(browser_cookies)} cookies extracted for API session")
    except Exception as e:
        print(f"   ⚠️  Cookie extraction error: {e}")

    try:
        ua = sb.cdp.get_user_agent()
        api_session.headers.update({
            "User-Agent": ua,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": SEARCH_PAGE_URL,
            "Origin": BASE_URL,
        })
    except Exception:
        pass

    return api_session


# -------------------------------------------------------------------
# SEARCH A SINGLE REPORT
# -------------------------------------------------------------------

def _search_single_report(sb, api_session: requests.Session, report_number: str):
    """
    Fill report number, solve CAPTCHA properly, submit,
    call API and return parsed record or None.
    """

    # ── Clear and fill report number ─────────────────────────────
    report_input_selectors = [
        "input[name='reportNumber']",
        "input[placeholder*='Report']",
        "input[id*='report']",
        "div.option-1 input",
        "div.option1 input",
        ".search-option:first-child input",
    ]

    filled = False
    for selector in report_input_selectors:
        try:
            sb.cdp.clear(selector)
            sb.cdp.type(selector, report_number)
            filled = True
            print(f"   ✏️  Filled report number via: {selector}")
            break
        except Exception:
            continue

    if not filled:
        # Try clicking first visible text input and typing
        try:
            sb.cdp.evaluate(f"""
                var inputs = document.querySelectorAll('input[type="text"]');
                if (inputs.length > 0) {{
                    inputs[0].focus();
                    inputs[0].value = '{report_number}';
                    inputs[0].dispatchEvent(new Event('input', {{bubbles: true}}));
                    inputs[0].dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            """)
            print(f"   ✏️  Filled report number via JS evaluate")
            filled = True
        except Exception as e:
            print(f"   ⚠️  Could not fill report number: {e}")

    sb.sleep(1)

    # ── Solve CAPTCHA properly ────────────────────────────────────
    print("   🤖 Solving CAPTCHA — please wait...")

    captcha_token = None

    # Method 1: SeleniumBase built-in solve_captcha
    try:
        sb.cdp.solve_captcha()
        sb.sleep(3)
        print("   ✅ solve_captcha() completed")
    except Exception as e:
        print(f"   ⚠️  solve_captcha() error: {e}")

    # Wait for CAPTCHA token to be populated (up to 30 seconds)
    print("   ⏳ Waiting for CAPTCHA token...")
    for attempt in range(30):
        try:
            token = sb.cdp.evaluate(
                "document.getElementById('g-recaptcha-response') ? "
                "document.getElementById('g-recaptcha-response').value : ''"
            )
            if token and len(token) > 50:
                captcha_token = token
                print(f"   ✅ CAPTCHA token obtained! (length: {len(token)})")
                break
        except Exception:
            pass

        # Also check inside iframes
        try:
            token = sb.cdp.evaluate("""
                (function() {
                    var iframes = document.querySelectorAll('iframe');
                    for (var i = 0; i < iframes.length; i++) {
                        try {
                            var doc = iframes[i].contentDocument || iframes[i].contentWindow.document;
                            var el = doc.getElementById('g-recaptcha-response');
                            if (el && el.value && el.value.length > 50) return el.value;
                        } catch(e) {}
                    }
                    return '';
                })()
            """)
            if token and len(token) > 50:
                captcha_token = token
                print(f"   ✅ CAPTCHA token found in iframe! (length: {len(token)})")
                break
        except Exception:
            pass

        time.sleep(1)

    if not captcha_token:
        print("   ⚠️  CAPTCHA token not found — trying gui_click_captcha as fallback")
        try:
            sb.cdp.gui_click_captcha()
            sb.sleep(5)
            # Try one more time to get token
            token = sb.cdp.evaluate(
                "document.getElementById('g-recaptcha-response') ? "
                "document.getElementById('g-recaptcha-response').value : ''"
            )
            if token and len(token) > 50:
                captcha_token = token
                print(f"   ✅ Token obtained after gui click! (length: {len(token)})")
        except Exception as e:
            print(f"   ⚠️  gui_click_captcha error: {e}")

    if not captcha_token:
        print("   ❌ Could not obtain CAPTCHA token — skipping this report")
        # Reload page for next attempt
        sb.cdp.open(SEARCH_PAGE_URL)
        sb.sleep(3)
        return None

    # ── Click Search button ───────────────────────────────────────
    print("   🔘 Clicking Search button...")
    search_selectors = [
        "button[type='submit']",
        "button.search-button",
        "button.btn-primary",
        "input[type='submit']",
        "button:contains('Search')",
    ]

    for selector in search_selectors:
        try:
            sb.cdp.click(selector)
            print(f"   ✅ Clicked Search via: {selector}")
            break
        except Exception:
            continue

    sb.sleep(3)

    # ── Call Search API with captcha token ────────────────────────
    print("   📡 Calling search API...")

    # Refresh cookies before API call
    try:
        browser_cookies = sb.cdp.get_all_cookies()
        for cookie in browser_cookies:
            api_session.cookies.set(
                cookie.get("name", ""),
                cookie.get("value", ""),
                domain="buycrash.lexisnexisrisk.com",
            )
    except Exception:
        pass

    payload = {
        "fields": {
            "state": STATE,
            "jurisdiction": JURISDICTION,
            "firstName": "",
            "lastName": "",
            "dateOfLoss": "",
            "accidentLocation1": "",
            "accidentLocation2": "",
            "reportNumber": report_number,
        },
        "captchaToken": captcha_token,
        "page": 1,
    }

    try:
        resp = api_session.post(SEARCH_API_URL, json=payload, timeout=30)

        if resp.status_code == 200:
            data = resp.json()
            records = data.get("data", {}).get("records", [])

            if records and len(records) > 0 and len(records[0]) > 0:
                record = records[0][0]
                record["reportTypeLabel"] = get_report_type_label(
                    record.get("reportType", "U")
                )
                print(f"   🎉 Report FOUND: {record.get('reportNumber')}")
                return record
            else:
                print(f"   ℹ️  No records found for report {report_number}")
                # Reload for next search
                sb.cdp.open(SEARCH_PAGE_URL)
                sb.sleep(3)
                return None
        else:
            print(f"   ⚠️  API returned HTTP {resp.status_code}: {resp.text[:200]}")
            sb.cdp.open(SEARCH_PAGE_URL)
            sb.sleep(3)
            return None

    except Exception as e:
        print(f"   ❌ API call error: {e}")
        sb.cdp.open(SEARCH_PAGE_URL)
        sb.sleep(3)
        return None