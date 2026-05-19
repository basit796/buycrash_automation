"""
searcher.py - Simple browser-only approach
1. Go to search URL
2. Fill report number
3. Solve captcha via 2Captcha
4. Click Search
5. Click OK on terms popup
6. Check if we got results or not
7. Repeat until 3 found
"""
import time
import requests
from seleniumbase import SB
from config import (
    USERNAME, get_password,
    BASE_URL, SEARCH_PAGE_URL,
    CAPTCHA_API_KEY, CAPTCHA_SITE_KEY,
    get_report_type_label, STATE, JURISDICTION,
)


# -------------------------------------------------------------------
# CAPTCHA — solve via 2Captcha service
# -------------------------------------------------------------------

def solve_recaptcha(page_url: str) -> str:
    """Submit to 2Captcha, poll until token returned."""
    if not CAPTCHA_API_KEY:
        raise Exception(
            "CAPTCHA_API_KEY missing in .env\n"
            "Sign up at 2captcha.com, add $3 credit, paste key in .env"
        )

    print("   🤖 Sending CAPTCHA to 2Captcha...")
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
    print(f"   ⏳ Task {task_id} — waiting for solution (15-30s)...")

    for attempt in range(24):  # max 2 minutes
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
            print(f"   ✅ CAPTCHA token received (length: {len(token)})")
            return token
        elif r.get("request") == "CAPCHA_NOT_READY":
            print(f"   ⏳ Not ready... ({(attempt+1)*5}s)")
        else:
            raise Exception(f"2Captcha poll error: {r}")

    raise Exception("2Captcha timeout after 2 minutes")


# -------------------------------------------------------------------
# LOGIN
# -------------------------------------------------------------------

def _do_login(sb):
    """Handle login including OTP if needed."""
    print("🔐 Logging in...")
    sb.activate_cdp_mode(BASE_URL + "/ui/home")
    sb.sleep(4)

    # Click Sign In button
    for strategy in [
        lambda: sb.cdp.find_element_by_text("Sign In").click(),
        lambda: sb.cdp.click("button:contains('Sign In')"),
    ]:
        try:
            strategy()
            print("   ✅ Clicked Sign In")
            break
        except Exception:
            continue
    sb.sleep(2)

    # Fill User ID
    for sel in ["input[placeholder='User ID']", "input[name='username']", "input[type='text']"]:
        try:
            sb.cdp.click(sel)
            sb.sleep(0.2)
            sb.cdp.type(sel, USERNAME)
            print(f"   ✅ Filled User ID: {USERNAME}")
            break
        except Exception:
            continue
    sb.sleep(0.3)

    # Fill Password
    for sel in ["input[placeholder='Password']", "input[name='password']", "input[type='password']"]:
        try:
            sb.cdp.click(sel)
            sb.sleep(0.2)
            sb.cdp.type(sel, get_password())
            print("   ✅ Filled Password")
            break
        except Exception:
            continue
    sb.sleep(0.3)

    # Submit
    for strategy in [
        lambda: sb.cdp.gui_click_element("button[type='submit']"),
        lambda: sb.cdp.evaluate("document.querySelector('button[type=\"submit\"]').click()"),
        lambda: sb.cdp.gui_press_key("Return"),
    ]:
        try:
            strategy()
            print("   ✅ Submitted login")
            break
        except Exception:
            continue

    sb.sleep(6)

    # Handle OTP if redirected
    url = sb.cdp.get_current_url()
    print(f"   📍 After login URL: {url}")

    if "otp" in url.lower():
        print("\n" + "="*50)
        print("  🔐 OTP REQUIRED!")
        print("  📱 Check your email/phone for OTP code")
        print("  ⌨️  Enter the OTP code in the browser window")
        print("  ✋  Waiting up to 2 minutes...")
        print("="*50 + "\n")

        for i in range(24):
            sb.sleep(5)
            current = sb.cdp.get_current_url()
            if "otp" not in current.lower():
                print(f"   ✅ OTP done! URL: {current}")
                break
            print(f"   ⏳ Waiting for OTP... ({(i+1)*5}s)")
        else:
            raise Exception("OTP timeout — took too long")

    print("   ✅ Login complete!")


# -------------------------------------------------------------------
# INJECT CAPTCHA TOKEN into page
# -------------------------------------------------------------------

def _inject_captcha_token(sb, token: str):
    """Inject the solved captcha token into the page."""
    sb.cdp.evaluate(f"""
        // Set token in all possible recaptcha response fields
        var fields = document.querySelectorAll('[name="g-recaptcha-response"]');
        fields.forEach(function(f) {{
            f.value = '{token}';
            f.innerHTML = '{token}';
        }});

        // Also try by ID
        var byId = document.getElementById('g-recaptcha-response');
        if (byId) {{
            byId.value = '{token}';
            byId.innerHTML = '{token}';
        }}

        // Trigger any recaptcha callback registered on the page
        if (typeof grecaptcha !== 'undefined') {{
            try {{
                var widgetId = Object.keys(___grecaptcha_cfg.clients)[0];
                var client = ___grecaptcha_cfg.clients[widgetId];
                // Find and call the callback
                var findCallback = function(obj) {{
                    for (var key in obj) {{
                        if (typeof obj[key] === 'object' && obj[key] !== null) {{
                            if (typeof obj[key].callback === 'function') {{
                                obj[key].callback('{token}');
                                return true;
                            }}
                            if (findCallback(obj[key])) return true;
                        }}
                    }}
                    return false;
                }};
                findCallback(client);
            }} catch(e) {{
                console.log('Captcha callback not found:', e);
            }}
        }}
    """)
    print("   ✅ Captcha token injected into page")


# -------------------------------------------------------------------
# SEARCH ONE REPORT — returns record dict or None
# -------------------------------------------------------------------

def _search_one_report(sb, report_number: str) -> dict:
    """
    Fill report number, solve captcha, click Search,
    handle terms popup, check result.
    Returns record dict if found, None if not found.
    """

    # ── Clear and fill report number ─────────────────────────────
    print(f"   ✏️  Filling report number: {report_number}")
    filled = False
    for sel in [
        "input[id*='reportNumber']",
        "input[name*='reportNumber']",
        "input[placeholder*='Report']",
        "input[id*='report']",
    ]:
        try:
            sb.cdp.click(sel)
            sb.sleep(0.2)
            # Clear existing value
            sb.cdp.evaluate(f"document.querySelector('{sel}').value = ''")
            sb.cdp.type(sel, report_number)
            filled = True
            print(f"   ✅ Filled via: {sel}")
            break
        except Exception:
            continue

    if not filled:
        # Fallback: set value via JS on first text input in option 1 section
        try:
            sb.cdp.evaluate(f"""
                var inputs = document.querySelectorAll('input[type="text"]');
                if (inputs.length > 0) {{
                    inputs[0].value = '{report_number}';
                    inputs[0].dispatchEvent(new Event('input', {{bubbles:true}}));
                    inputs[0].dispatchEvent(new Event('change', {{bubbles:true}}));
                }}
            """)
            print("   ✅ Filled via JS fallback")
        except Exception as e:
            print(f"   ⚠️  Could not fill report number: {e}")

    sb.sleep(1)

    # ── Solve CAPTCHA ─────────────────────────────────────────────
    token = solve_recaptcha(SEARCH_PAGE_URL)

    # ── Inject token into page ────────────────────────────────────
    _inject_captcha_token(sb, token)
    sb.sleep(1)

    # ── Click Search button ───────────────────────────────────────
    print("   🔘 Clicking Search...")
    for sel in [
        "button[type='submit']",
        "button:contains('Search')",
        "button.search-btn",
        ".search-button",
    ]:
        try:
            sb.cdp.click(sel)
            print(f"   ✅ Clicked Search via: {sel}")
            break
        except Exception:
            continue

    sb.sleep(3)

    # ── Handle Terms & Conditions popup ──────────────────────────
    print("   📋 Checking for Terms popup...")
    for ok_sel in [
        "button:contains('OK')",
        "button:contains('Ok')",
        "button:contains('Accept')",
        "button:contains('Agree')",
        "button:contains('Continue')",
        ".modal button[type='submit']",
        ".modal .btn-primary",
        "dialog button",
    ]:
        try:
            sb.cdp.click_if_visible(ok_sel)
            print(f"   ✅ Clicked OK/Accept on popup")
            break
        except Exception:
            continue

    sb.sleep(3)

    # ── Check result ──────────────────────────────────────────────
    current_url = sb.cdp.get_current_url()
    print(f"   📍 URL after search: {current_url}")

    # Check 1: Did URL change to a results/detail page?
    if "result" in current_url or "detail" in current_url or "report" in current_url.split("search")[1] if "search" in current_url else False:
        print("   🎉 URL changed — report likely found!")
        # Extract data from page
        return _extract_from_page(sb, report_number)

    # Check 2: Look for result elements on page
    try:
        page_text = sb.cdp.get_text("body")

        # Signs of NO result
        no_result_phrases = [
            "no results",
            "no records found",
            "0 results",
            "not found",
            "no reports found",
        ]
        for phrase in no_result_phrases:
            if phrase.lower() in page_text.lower():
                print(f"   ❌ No results found (detected: '{phrase}')")
                return None

        # Signs of a RESULT
        result_phrases = [
            "date of incident",
            "report number",
            "accident location",
            "dateofincident",
        ]
        for phrase in result_phrases:
            if phrase.lower() in page_text.lower():
                print("   🎉 Result data detected on page!")
                return _extract_from_page(sb, report_number)

    except Exception as e:
        print(f"   ⚠️  Page text check error: {e}")

    # Check 3: Look for result table/card elements
    result_selectors = [
        ".search-result",
        ".result-card",
        ".report-result",
        "table.results",
        "[class*='result']",
        "[class*='record']",
    ]
    for sel in result_selectors:
        try:
            if sb.cdp.is_element_visible(sel):
                print(f"   🎉 Result element found: {sel}")
                return _extract_from_page(sb, report_number)
        except Exception:
            continue

    print(f"   ❌ No report found for {report_number}")
    return None


# -------------------------------------------------------------------
# EXTRACT DATA FROM RESULT PAGE
# -------------------------------------------------------------------

def _extract_from_page(sb, report_number: str) -> dict:
    """
    Extract report details from the result page.
    Returns a dict with the data we need.
    """
    record = {
        "reportNumber":    report_number,
        "reportType":      "",
        "reportTypeLabel": "",
        "dateOfIncident":  "",
        "street":          "",
        "crossStreet":     "",
        "lastNames":       [],
        "jurisdiction":    "DETROIT POLICE DEPARTMENT",
    }

    try:
        page_text = sb.cdp.get_text("body")

        # Try to get structured data from page
        # Look for common field patterns
        import re

        # Date pattern
        date_match = re.search(
            r'(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})',
            page_text
        )
        if date_match:
            record["dateOfIncident"] = date_match.group(1)

        # Try to get page source for more detail
        html = sb.cdp.get_html()

        # Look for report type
        if "Accident" in page_text:
            record["reportType"]      = "A"
            record["reportTypeLabel"] = "Accident Report"
        elif "Fatal" in page_text:
            record["reportType"]      = "F"
            record["reportTypeLabel"] = "Fatal Accident Report"
        else:
            record["reportType"]      = "A"
            record["reportTypeLabel"] = "Accident Report"

        print(f"   📄 Extracted: date={record['dateOfIncident']}, "
              f"type={record['reportTypeLabel']}")

    except Exception as e:
        print(f"   ⚠️  Extraction error: {e}")

    return record


# -------------------------------------------------------------------
# MAIN ENTRY POINT
# -------------------------------------------------------------------

def run_search_session(report_numbers: list,
                       found_callback,
                       not_found_callback) -> int:
    """
    Single browser session — login once, search all report numbers.
    Returns count of found reports.
    """
    found_count = 0

    with SB(uc=True, test=False, locale="en", headless=False) as sb:

        # Login once
        _do_login(sb)

        # Go to search page
        print(f"\n🌐 Going to search page...")
        sb.cdp.open(SEARCH_PAGE_URL)
        sb.sleep(4)
        print(f"   ✅ On search page")

        # Loop through report numbers
        for report_num in report_numbers:
            report_str = str(report_num)
            print(f"\n{'='*50}")
            print(f"🔍 Report: {report_str}")
            print(f"{'='*50}")

            try:
                record = _search_one_report(sb, report_str)

                if record is not None:
                    found_count += 1
                    found_callback(record)
                    print(f"   🎉 Total found so far: {found_count}")
                else:
                    not_found_callback(report_str)

            except KeyboardInterrupt:
                print("\n⛔ Stopped by user")
                break
            except Exception as e:
                print(f"   ⚠️  Error: {e}")
                not_found_callback(report_str)

            # Go back to search page for next report
            print(f"   🔄 Reloading search page for next report...")
            try:
                sb.cdp.open(SEARCH_PAGE_URL)
                sb.sleep(3)
            except Exception:
                pass

            time.sleep(1)

    return found_count