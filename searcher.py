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
            print(f"   ✅ CAPTCHA token received (length: {len(token)})")
            return token
        elif r.get("request") == "CAPCHA_NOT_READY":
            print(f"   ⏳ Not ready... ({(attempt+1)*12}s)")
        else:
            raise Exception(f"2Captcha poll error: {r}")

    raise Exception("2Captcha timeout after 4 minutes")


# -------------------------------------------------------------------
# OTP HANDLER — reads code from Google Sheet cell B2
# -------------------------------------------------------------------

def _handle_otp(sb):
    """
    Full OTP flow:
    1. Make sure Email radio is selected
    2. Click 'Send Code and Continue'
    3. Instruct user to paste OTP into Google Sheet (Start Number tab, cell B2)
    4. Poll that cell every 12s until a 6-digit code appears (4 min timeout)
    5. Fill the Passcode field and submit
    """
    import sheets_handler

    print("")
    print("=" * 55)
    print("  OTP REQUIRED — Unrecognized Location")
    print("=" * 55)

    # ── Step 1: Select Email radio button ────────────────────────
    print("   Selecting Email as OTP channel...")
    for sel in [
        "input[type='radio'][value*='mail']",
        "input[type='radio']:first-of-type",
    ]:
        try:
            sb.cdp.click(sel)
            print("   Email radio selected")
            sb.sleep(0.5)
            break
        except Exception:
            continue

    # ── Step 2: Click 'Send Code and Continue' ────────────────────
    print("   Clicking 'Send Code and Continue'...")
    sent = False
    for sel in [
        "button:contains('Send Code')",
        "button:contains('Send Code and Continue')",
        "input[type='submit']",
        "button[type='submit']",
    ]:
        try:
            sb.cdp.click(sel)
            print("   Clicked Send Code button")
            sent = True
            sb.sleep(2)
            break
        except Exception:
            continue

    if not sent:
        # Fallback: Tab then Enter from radio
        try:
            sb.cdp.gui_press_key("Tab")
            sb.sleep(0.3)
            sb.cdp.gui_press_key("Return")
            print("   Sent via Tab + Enter fallback")
            sb.sleep(2)
        except Exception as e:
            print(f"   WARNING: Could not click Send Code: {e}")

    # ── Step 3: Tell user to paste OTP into Google Sheet ─────────
    print("")
    print("-" * 55)
    print("  ACTION REQUIRED:")
    print("  An OTP has been sent to your email.")
    print("  Open the Google Sheet -> 'Start Number' tab")
    print("  Paste the OTP code into cell B2")
    print("  (The script will read it automatically)")
    print("-" * 55)
    print("")

    # ── Step 4: Poll Google Sheet B2 for the OTP ─────────────────
    otp_code = None
    max_attempts = 24   # 24 x 12s = 4 minutes
    for attempt in range(max_attempts):
        sb.sleep(12)
        otp_code = sheets_handler.get_otp_from_sheet()
        if otp_code:
            print(f"   OTP received from Google Sheet: {otp_code}")
            break
        print(f"   Waiting for OTP in Sheet B2... ({(attempt+1)*12}s / {max_attempts*12}s)")
    else:
        raise Exception("OTP timeout: no code found in Google Sheet cell B2 after 4 minutes")

    # ── Step 5: Wait for Verify Authentication page ─────────────
    print("   Waiting for Verify Authentication page...")
    for i in range(15):
        sb.sleep(1)
        try:
            body_text = sb.cdp.get_text("body")
            if "Verify Authentication" in body_text or "Passcode" in body_text:
                print("   Verify Authentication page loaded")
                break
        except Exception:
            pass
    else:
        print("   WARNING: Verify Authentication page may not have loaded, trying anyway...")

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

    # Fill Passcode — Method 2: JS fills first visible text input on page
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

    # Fill Passcode — Method 3: broadest fallback
    if not filled:
        try:
            sb.cdp.click("input")
            sb.sleep(0.2)
            sb.cdp.type("input", otp_code)
            print("   OTP filled via generic input selector")
            filled = True
        except Exception as e:
            print(f"   Generic fill failed: {e}")

    if not filled:
        print("   WARNING: Could not find Passcode field — OTP not entered")
        return

    sb.sleep(0.5)

    # Submit — click Submit button
    submitted = False
    if not submitted:
        for btn_sel in [
            "button:contains('Submit')",
            "button:contains('Verify')",
            "button:contains('Continue')",
            "button[type='submit']",
        ]:
            try:
                sb.cdp.click(btn_sel)
                print(f"   OTP submitted via button: {btn_sel}")
                submitted = True
                break
            except Exception:
                continue

    sb.sleep(5)

    # Verify we left the OTP page
    current = sb.cdp.get_current_url()
    if "otp" in current.lower() or "verify" in current.lower():
        print(f"   WARNING: May still be on OTP/verify page: {current}")
    else:
        print(f"   OTP complete! Redirected to: {current}")

    # Clear B2 so stale code is not reused next time
    try:
        sheets_handler.clear_otp_from_sheet()
        print("   Cleared OTP from Google Sheet B2")
    except Exception:
        pass


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
    submitted = False

    # First try pressing Enter on password field
    for sel in [
        "input[placeholder='Password']",
        "input[name='password']",
        "input[type='password']"
    ]:
        try:
            sb.cdp.click(sel)
            sb.sleep(0.2)
            sb.cdp.press_keys(sel, "\n")
            print("   ✅ Pressed Enter to submit login")
            submitted = True
            break
        except Exception:
            continue

    # Fallback: click Sign In button
    if not submitted:
        for strategy in [
            lambda: sb.cdp.find_element_by_text("Sign In").click(),
            lambda: sb.cdp.gui_click_element("button[type='submit']"),
            lambda: sb.cdp.click("button[type='submit']"),
            lambda: sb.cdp.evaluate("""
                (() => {
                    const btn =
                        [...document.querySelectorAll('button')]
                        .find(b => b.innerText.includes('Sign In'));
                    if (btn) btn.click();
                })()
            """),
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
    print(f"   After login URL: {url}")

    if "otp" in url.lower():
        _handle_otp(sb)

    print("   Login complete!")


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

    sb.sleep(30)

    # -- Check result ------------------------------------------------
    current_url = sb.cdp.get_current_url()
    print(f"   URL after search: {current_url}")

    try:
        page_text = sb.cdp.get_text("body")
    except Exception as e:
        print(f"   Could not read page text: {e}")
        return None

    page_lower = page_text.lower()

    # PRIMARY: "N records found" - the most reliable signal on this site
    import re as _re2
    count_match = _re2.search(r'(\d+)\s+records?\s+found', page_lower)
    if count_match:
        count = int(count_match.group(1))
        if count == 0:
            print(f"   NOT FOUND - 0 records found")
            return None
        else:
            print(f"   FOUND - {count} records found")
            return _extract_from_page(sb, report_number)

    # FALLBACK 1: explicit no-result phrases
    for phrase in ["no results", "no records found", "0 results", "no reports found"]:
        if phrase in page_lower:
            print(f"   NOT FOUND (phrase: {phrase})")
            return None

    # FALLBACK 2: URL navigated to /results page
    if "/results" in current_url or "/report/detail" in current_url:
        print("   FOUND - URL changed to results page")
        return _extract_from_page(sb, report_number)

    # FALLBACK 3: Add to Cart button = result row exists
    if "add to cart" in page_lower:
        print("   FOUND - Add to Cart button detected")
        return _extract_from_page(sb, report_number)

    print(f"   NOT FOUND - no result signals for {report_number}")
    return None
    return None


# -------------------------------------------------------------------
# EXTRACT DATA FROM RESULT PAGE
# -------------------------------------------------------------------

def _extract_from_page(sb, report_number: str) -> dict:
    """
    Extract report details from the result page.
    Returns a dict with the data we need.
    """
    import re, json as _json

    record = {
        "reportNumber":    report_number,
        "reportType":      "A",
        "reportTypeLabel": "Accident Report",
        "dateOfIncident":  "",
        "street":          "",
        "crossStreet":     "",
        "lastNames":       [],
        "jurisdiction":    "DETROIT POLICE DEPARTMENT",
    }

    # ── Method 1: JavaScript table extraction ────────────────────
    try:
        js_result = sb.cdp.evaluate("""
            (function() {
                var result = {reportType:'', lastNames:'', doi:'', location:''};
                var trs = Array.from(document.querySelectorAll('tr'));
                for (var i = 0; i < trs.length; i++) {
                    var tds = Array.from(trs[i].querySelectorAll('td'));
                    if (tds.length < 3) continue;
                    var rowTxt = trs[i].innerText || '';
                    if (!/\\d{2}\\/\\d{2}\\/\\d{4}/.test(rowTxt)) continue;
                    // data row found
                    result.reportType = tds[0].innerText.replace(/Add to Cart/gi,'').trim();
                    result.lastNames  = tds[1] ? tds[1].innerText.trim() : '';
                    result.doi        = tds[2] ? tds[2].innerText.trim() : '';
                    result.location   = tds[3] ? tds[3].innerText.trim() : '';
                    break;
                }
                return JSON.stringify(result);
            })()
        """)

        if js_result and js_result != 'null':
            d = _json.loads(js_result)

            rt = d.get('reportType', '')
            if rt:
                record['reportTypeLabel'] = rt
                record['reportType'] = 'F' if 'Fatal' in rt else 'A'

            doi = re.search(r'\d{2}/\d{2}/\d{4}', d.get('doi', ''))
            if doi:
                record['dateOfIncident'] = doi.group(0)

            raw_names = d.get('lastNames', '')
            if raw_names:
                record['lastNames'] = [n.strip() for n in re.split(r'[;,]', raw_names) if n.strip()]

            loc_lines = [l.strip() for l in d.get('location', '').splitlines() if l.strip()]
            if loc_lines:
                parts = [p.strip() for p in loc_lines[0].split('/')]
                record['street']      = parts[0] if parts else ''
                record['crossStreet'] = parts[1] if len(parts) > 1 else ''
            if len(loc_lines) > 1:
                record['jurisdiction'] = loc_lines[-1]

            print(f"   Extracted: date={record['dateOfIncident']}, "
                  f"type={record['reportTypeLabel']}, "
                  f"names={record['lastNames']}")

    except Exception as e:
        print(f"   JS extraction error: {e}")

    # ── Method 2: Regex fallback on page text ────────────────────
    if not record['dateOfIncident']:
        try:
            page_text = sb.cdp.get_text("body")
            m = re.search(r'(\d{2}/\d{2}/\d{4})', page_text)
            if m:
                record['dateOfIncident'] = m.group(1)
            if 'Fatal' in page_text:
                record['reportType'] = 'F'
                record['reportTypeLabel'] = 'Fatal Accident Report'
            print(f"   Regex fallback: date={record['dateOfIncident']}")
        except Exception as e:
            print(f"   Regex extraction error: {e}")

    return record


# -------------------------------------------------------------------
# MAIN ENTRY POINT
# -------------------------------------------------------------------

def run_search_session(report_numbers: list,
                       found_callback,
                       not_found_callback,
                       found_so_far: int = 0,
                       target: int = 3) -> int:
    """
    Single browser session — login once, search all report numbers.
    found_so_far : global count of found reports BEFORE this batch.
    target       : stop everything when found_so_far + found_count >= target.
    Returns count of found reports in THIS batch.
    """
    found_count = 0

    with SB(uc=True, test=False, locale="en", headless=False) as sb:

        # Login once
        _do_login(sb)

        # Go to search page
        print("\nGoing to search page...")
        sb.cdp.open(SEARCH_PAGE_URL)
        sb.sleep(4)
        print("   On search page")

        # Loop through report numbers
        for report_num in report_numbers:

            # Global stop check — reached target before finishing batch
            if found_so_far + found_count >= target:
                print(f"\n*** TARGET REACHED ({target} found) — stopping batch early ***")
                break

            report_str = str(report_num)
            print(f"\n{'='*50}")
            print(f"Checking report: {report_str}")
            print(f"{'='*50}")

            try:
                record = _search_one_report(sb, report_str)

                if record is not None:
                    found_count += 1
                    found_callback(record)
                    print(f"   Found in this batch: {found_count}  |  Global total: {found_so_far + found_count}/{target}")

                    # Stop immediately if we've hit the global target
                    if found_so_far + found_count >= target:
                        print(f"\n*** GLOBAL TARGET {target} REACHED — stopping now ***")
                        break
                else:
                    not_found_callback(report_str)

            except KeyboardInterrupt:
                print("\nStopped by user")
                break
            except Exception as e:
                print(f"   Error on {report_str}: {e}")
                not_found_callback(report_str)

            # Reload search page for next report
            print("   Reloading search page...")
            try:
                sb.cdp.open(SEARCH_PAGE_URL)
                sb.sleep(3)
            except Exception:
                pass

            time.sleep(1)

    return found_count