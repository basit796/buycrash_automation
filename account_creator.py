"""
account_creator.py
------------------
Automates account creation on buycrash.lexisnexisrisk.com using SeleniumBase CDP mode and Mail.tm disposable emails.
Loads USA billing address pools, name pools, and password pools. Logs registered accounts directly to the "Credentials" Google Sheet.
"""
import ipaddress
from _pytest import subtests
import re
import time
import random
import requests
from datetime import datetime
from seleniumbase import SB
import mailreader
import sheets_handler

# ===================================================================
# DATA POOLS
# ===================================================================

FIRST_NAMES = [
    "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles", "Christopher",
    "Daniel", "Matthew", "Anthony", "Mark", "Donald", "Steven", "Paul", "Andrew", "Joshua", "Kenneth",
    "Kevin", "Brian", "George", "Edward", "Ronald", "Timothy", "Jason", "Jeffrey", "Ryan", "Jacob",
    "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen",
    "Nancy", "Lisa", "Betty", "Margaret", "Sandra", "Ashley", "Kimberly", "Emily", "Donna", "Michelle",
    "Carol", "Amanda", "Dorothy", "Melissa", "Deborah", "Stephanie", "Rebecca", "Sharon", "Laura", "Cynthia"
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
    "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
    "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts",
    "Gomez", "Phillips", "Evans", "Diaz", "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart"
]

ADDRESSES = [
    {"street": "1421 Lafayette Blvd", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "834 Woodward Ave", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "2250 E Grand Blvd", "city": "Detroit", "state": "MI", "zip": "48211"},
    {"street": "5901 Cass Ave", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "11000 W McNichols Rd", "city": "Detroit", "state": "MI", "zip": "48221"},
    {"street": "3400 E Jefferson Ave", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "900 Bagley Ave", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "7310 W Vernor Hwy", "city": "Detroit", "state": "MI", "zip": "48209"},
    {"street": "19701 W 7 Mile Rd", "city": "Detroit", "state": "MI", "zip": "48219"},
    {"street": "14600 Fenkell Ave", "city": "Detroit", "state": "MI", "zip": "48227"},
    {"street": "4201 Davison St", "city": "Detroit", "state": "MI", "zip": "48238"},
    {"street": "8100 E Jefferson Ave", "city": "Detroit", "state": "MI", "zip": "48214"},
    {"street": "2934 Rosa Parks Blvd", "city": "Detroit", "state": "MI", "zip": "48216"},
    {"street": "16101 Harper Ave", "city": "Detroit", "state": "MI", "zip": "48224"},
    {"street": "6101 Tireman Ave", "city": "Detroit", "state": "MI", "zip": "48204"},
    {"street": "21000 Mack Ave", "city": "Grosse Pointe", "state": "MI", "zip": "48236"},
    {"street": "3100 Gratiot Ave", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "10200 W Outer Dr", "city": "Detroit", "state": "MI", "zip": "48223"},
    {"street": "25 Peterboro St", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "1150 Griswold St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "1001 Woodward Ave", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "150 W Jefferson Ave", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "500 Griswold St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "660 Woodward Ave", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "211 W Fort St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "645 Griswold St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "400 Monroe St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "555 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "1200 Washington Blvd", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "230 E Grand River Ave", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "1407 Randolph St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "350 Madison St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "1300 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "1400 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "1500 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "1600 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "1900 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "2140 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "2200 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "2300 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "2400 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "2500 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "2600 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "2700 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "2800 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "2900 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "3000 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "3100 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "3200 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "3300 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "3400 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "3500 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "3600 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "3700 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "3800 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "3900 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "4000 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "4100 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "4200 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "4300 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "4400 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48207"}
]

PASSWORDS = [
    "Secure12!", "Pilot34@b", "Kappa78#A", "Delta91$z", "Alpha23%X",
    "Bravo56^q", "Gamma09&W", "Hotel47*m", "India82!P", "Juliet15@n",
    "Kilo63#V", "Lima29$c", "Mike74%R", "Nova38^k", "Oscar51&T",
    "Papa17*s", "Quebec66!B", "Romeo43@y", "Sierra81#N", "Tango22$j",
    "Uniform95%H", "Victor37^d", "Whiskey54&L", "Xray68*f", "Yankee11!G",
    "Zebra22#q", "Apple88$k", "Baker77%m", "Charlie99^p", "Delta88&t",
    "Echo11!z", "Foxtrot33@r", "Golf44#v", "Hotel55$w", "India66%x",
    "Juliet77^y", "Kilo88&a", "Lima99*b", "Mike11!c", "November22@d",
    "Oscar33#e", "Papa44$f", "Quebec55%g", "Romeo66^h", "Sierra77&i",
    "Tango88*j", "Uniform99!k", "Victor11@l", "Whiskey22#m", "Xray33$n",
    "Yankee44%o", "Zulu55^p", "Amber88&q", "Bronze99*r", "Copper11!s",
    "Diamond22@t", "Emerald33#u", "Falcon44$v", "Gold55%w", "Silver66^x",
    "Platinum77&y", "Titanium88*z"
]

STATE_INDEX = {
    "AL": 1, "AK": 2, "AZ": 3, "AR": 4, "CA": 5, "CO": 6, "CT": 7,
    "DE": 8, "FL": 9, "GA": 10, "HI": 11, "ID": 12, "IL": 13, "IN": 14,
    "IA": 15, "KS": 16, "KY": 17, "LA": 18, "ME": 19, "MD": 20,
    "MA": 21, "MI": 22, "MN": 23, "MS": 24, "MO": 25, "MT": 26,
    "NE": 27, "NV": 28, "NH": 29, "NJ": 30, "NM": 31, "NY": 32,
    "NC": 33, "ND": 34, "OH": 35, "OK": 36, "OR": 37, "PA": 38,
    "RI": 39, "SC": 40, "SD": 41, "TN": 42, "TX": 43, "UT": 44,
    "VT": 45, "VA": 46, "WA": 47, "WV": 48, "WI": 49, "WY": 50,
}

# ===================================================================
# CORE AUTOMATION FLOW
# ===================================================================

def generate_user_id(email: str) -> str:
    """
    User ID Rule:
    - Starts with letter
    - 7 to 20 characters
    - Alpha-numeric only
    """
    prefix = email.split("@")[0]
    user_id = re.sub(r"[^a-zA-Z0-9]", "", prefix)
    if not user_id or not user_id[0].isalpha():
        user_id = "a" + user_id
    
    # Restrict to first 14 characters as per spec
    user_id = user_id[:14]
    
    # Guarantee minimum 7 chars
    if len(user_id) < 7:
        user_id = (user_id + "1234567")[:7]
    return user_id


def create_one_account(proxy: str = None) -> dict:
    """
    Performs the full Mail.tm creation + BuyCrash registration + OTP submission.
    """
    print("\n[CREATOR] Starting creation sequence...")
    
    # 1. Choose Random values
    first_name = random.choice(FIRST_NAMES)
    last_name  = random.choice(LAST_NAMES)
    while last_name == first_name:
        last_name = random.choice(LAST_NAMES)
        
    address = random.choice(ADDRESSES)
    portal_pass = random.choice(PASSWORDS)
    phone = "313" + "".join(random.choices("0123456789", k=7))
    
    # 2. Create Mail.tm account
    print("[CREATOR] Creating Mail.tm disposable email account...")
    mail_acc = mailreader.create_account(password=portal_pass)
    email = mail_acc["email"]
    email_pass = mail_acc["password"]
    mailtm_token = mail_acc["token"]
    print(f"[CREATOR] Generated email: {email}")
    
    user_id = generate_user_id(email)
    print(f"[CREATOR] Generated User ID: {user_id}")
    
    # 3. SeleniumBase registration
    registration_url = "https://buycrash.lexisnexisrisk.com/ui/auth/registration"
    
    # Use residential proxy if configured
    sb_proxy = None
    if proxy:
        # Standardize formatting for SeleniumBase: user:pass@host:port
        clean_proxy = proxy.replace("http://", "").replace("https://", "")
        sb_proxy = clean_proxy
        print(f"[CREATOR] Using proxy: {sb_proxy.split('@')[-1] if '@' in sb_proxy else sb_proxy}")

    with SB(uc=True, test=False, locale="en", headless=False, proxy=sb_proxy) as sb:
        print(f"[CREATOR] Opening registration page: {registration_url}")
        sb.activate_cdp_mode(registration_url)
        sb.sleep(4)
        
        # --- Step 1: Radio button & initial email input ---
        print("[CREATOR] Selecting Involved Party radio...")
        radio_clicked = False
        for sel in ["input[id='involvedParty']", "input[value='Involved Party']", "label:contains('Involved Party')"]:
            try:
                sb.cdp.click(sel)
                radio_clicked = True
                break
            except Exception:
                continue
        if not radio_clicked:
            try:
                sb.cdp.evaluate('document.querySelector("input[id=\'involvedParty\']").click();')
                print("[CREATOR] Radio clicked via JS")
            except Exception as e:
                print(f"[CREATOR] Radio click fallback error: {e}")
                
        sb.sleep(0.5)
        
        print("[CREATOR] Entering initial email...")
        email_entered = False
        for sel in ["input[name='email']", "input[id='email']", "input[type='text']"]:
            try:
                sb.cdp.click(sel)
                sb.sleep(0.2)
                sb.cdp.type(sel, email)
                email_entered = True
                break
            except Exception:
                continue
        if not email_entered:
            try:
                sb.cdp.evaluate(f'document.querySelector("input[name=\'email\']").value = "{email}";')
            except Exception as e:
                print(f"[CREATOR] Email fallback error: {e}")
                
        sb.sleep(0.5)
        
        print("[CREATOR] Clicking initial Continue...")
        btn_clicked = False
        for sel in ["button:contains('Continue Registration')", "input[value='Continue Registration']", "button[type='submit']"]:
            try:
                sb.cdp.click(sel)
                btn_clicked = True
                break
            except Exception:
                continue
        if not btn_clicked:
            try:
                sb.cdp.evaluate('document.querySelector("button[type=\'submit\']").click();')
            except Exception as e:
                print(f"[CREATOR] Continue fallback error: {e}")
                
        sb.sleep(5)
        all_inputs = sb.cdp.evaluate("""
            (function() {
                var inputs = document.querySelectorAll('input, select');
                var result = [];
                for (var i = 0; i < inputs.length; i++) {
                    var el = inputs[i];
                    result.push(el.tagName + ' | name=' + (el.name||'') + 
                            ' | id=' + (el.id||'') + 
                            ' | type=' + (el.type||'') +
                            ' | formcontrolname=' + (el.getAttribute('formcontrolname')||''));
                }
                return result.join('\\n');
            })();
        """)
        print(f"[CREATOR] All form fields:\n{all_inputs}")

        state_debug = sb.cdp.evaluate("""
            (function() {
                var selects = document.querySelectorAll('select');
                var result = [];
                for (var i = 0; i < selects.length; i++) {
                    result.push('SELECT #' + i + ' id=' + selects[i].id + 
                               ' options=' + selects[i].options.length +
                               ' first3=' + Array.from(selects[i].options).slice(0,3).map(o=>o.value+'|'+o.text).join(','));
                }
                return result.join('\\n');
            })();
        """)
        print(f"[CREATOR] Selects found:\n{state_debug}")

        mat_select_debug = sb.cdp.evaluate("""
            (function() {
                var els = document.querySelectorAll('mat-select, .mat-mdc-select, [role="listbox"], [role="combobox"]');
                var result = [];
                for (var i = 0; i < els.length; i++) {
                    result.push('EL #' + i + ': ' + els[i].tagName + 
                               ' | id=' + els[i].id +
                               ' | class=' + els[i].className.substring(0,80) +
                               ' | aria-label=' + (els[i].getAttribute('aria-label')||'') +
                               ' | aria-labelledby=' + (els[i].getAttribute('aria-labelledby')||''));
                }
                return result.length ? result.join('\\n') : 'NONE FOUND';
            })();
        """)
        print(f"[CREATOR] Mat-select elements:\n{mat_select_debug}")

        # --- Step 2: The long registration form ---
        print("[CREATOR] Processing the long registration form...")

        # First Name
        sb.cdp.click("#firstName"); sb.sleep(0.2); sb.cdp.type("#firstName", first_name)

        # Last Name
        sb.cdp.click("#lastName"); sb.sleep(0.2); sb.cdp.type("#lastName", last_name)

        # Phone
        sb.cdp.click("#phone"); sb.sleep(0.2); sb.cdp.type("#phone", phone)

        # Street Address
        sb.cdp.click("#streetAddress1"); sb.sleep(0.2); sb.cdp.type("#streetAddress1", address["street"])

        # City
        sb.cdp.click("#city"); sb.sleep(0.2); sb.cdp.type("#city", address["city"])

        # State — find the select by querying ALL selects, pick the state one
        try:
            state_index = STATE_INDEX.get(address["state"], 22)
            sb.cdp.evaluate(f"""
                (function() {{
                    var selects = document.querySelectorAll('select');
                    for (var i = 0; i < selects.length; i++) {{
                        var s = selects[i];
                        // Skip country dropdown (has "United States" as option)
                        var isCountry = false;
                        for (var o = 0; o < s.options.length; o++) {{
                            if (s.options[o].text.includes('United States')) {{
                                isCountry = true; break;
                            }}
                        }}
                        if (!isCountry && s.options.length > 10) {{
                            s.focus();
                            s.selectedIndex = {state_index};
                            s.dispatchEvent(new Event('change', {{bubbles: true}}));
                            s.dispatchEvent(new Event('input', {{bubbles: true}}));
                            s.dispatchEvent(new Event('blur', {{bubbles: true}}));
                            console.log('State set to index {state_index}: ' + s.options[{state_index}].text);
                            return;
                        }}
                    }}
                }})();
            """)
            print(f"[CREATOR] State set: {address['state']} (index {state_index})")
        except Exception as e:
            print(f"[CREATOR] State error: {e}")

        # Zip
        sb.cdp.click("#zipCode"); sb.sleep(0.2); sb.cdp.type("#zipCode", address["zip"])

        # Portal User ID
        sb.cdp.click("#loginId"); sb.sleep(0.2); sb.cdp.type("#loginId", user_id)

        # Password
        sb.cdp.click("#password"); sb.sleep(0.2); sb.cdp.type("#password", portal_pass)

        # Confirm Password
        sb.cdp.click("#passwordConfirm"); sb.sleep(0.2); sb.cdp.type("#passwordConfirm", portal_pass)

        # OTP - select Email as Default (mat-radio-4-input is the Default radio next to email)
        try:
            sb.cdp.click("#mat-radio-4-input")
            print("[CREATOR] OTP email Default radio selected")
        except Exception as e:
            print(f"[CREATOR] OTP radio error: {e}")
        
        sb.sleep(0.3)

        # Terms checkbox
        try:
            sb.cdp.click("#mat-mdc-checkbox-0-input")
            print("[CREATOR] Terms checkbox checked")
        except Exception as e:
            print(f"[CREATOR] Checkbox error: {e}")

        sb.sleep(0.5)

        # Submit - scroll down first, then click the Continue Registration button by text
        # Scroll to bottom first
        sb.cdp.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        sb.sleep(1)

        # Click Continue Registration by finding button with exact text
        sb.cdp.evaluate("""
            (function() {
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    if (btns[i].textContent.trim() === 'Continue Registration') {
                        btns[i].scrollIntoView();
                        btns[i].click();
                        console.log('Clicked Continue Registration button #' + i);
                        return;
                    }
                }
                console.log('Continue Registration button NOT found');
            })();
        """)
        print("[CREATOR] Continue Registration clicked via exact text match")

        print("[CREATOR] Form submitted. Waiting for OTP page to load...")
        sb.sleep(6)

        # --- Step 3: Fetch OTP and verify ---
        print("[CREATOR] Polling Mail.tm for 6-digit OTP...")
        otp = mailreader.wait_for_otp(token=mailtm_token, max_wait_sec=120)
        
        if not otp:
            print("[CREATOR] ERROR: Did not receive OTP email.")
            sb.save_screenshot("creator_error_no_otp.png")
            raise Exception("OTP timeout — verification failed")
            
        print(f"[CREATOR] Got OTP passcode: {otp}")
        
        # Enter OTP Passcode
        otp_filled = False
        for sel in ["input[name='passcode']", "input[placeholder='Passcode']", "input[type='text']"]:
            try:
                sb.cdp.click(sel); sb.sleep(0.2); sb.cdp.type(sel, otp)
                otp_filled = True; break
            except Exception:
                continue
        if not otp_filled:
            sb.cdp.evaluate(f'document.querySelector("input[name=\'passcode\']").value = "{otp}";')
            
        sb.sleep(0.5)
        
        # Click OTP Submit
        otp_submitted = False
        for sel in ["button:contains('Submit')", "button[type='submit']"]:
            try:
                sb.cdp.click(sel)
                otp_submitted = True; break
            except Exception:
                continue
        if not otp_submitted:
            sb.cdp.evaluate('document.querySelector("button[type=\'submit\']").click();')
            
        sb.sleep(8)
        print("[CREATOR] Registration submitted successfully!")
        
        # 4. Save details to Sheets "Credentials" page
        billing_address = f"{address['street']}, {address['city']}, {address['state']} {address['zip']}"
        sheets_handler.save_created_account(
            email=email,
            email_pass=email_pass,
            portal_user=user_id,
            portal_pass=portal_pass,
            address=billing_address,
            first_name=first_name,
            last_name=last_name
        )
        
        return {
            "email": email,
            "email_pass": email_pass,
            "user_id": user_id,
            "portal_pass": portal_pass,
            "address": billing_address,
            "first_name": first_name,
            "last_name": last_name
        }


def create_multiple_accounts(count: int = 6, proxy: str = None) -> list:
    """
    Wrapper to create multiple accounts back-to-back.
    """
    created_list = []
    for i in range(1, count + 1):
        print(f"\n{'='*60}")
        print(f"  CREATING ACCOUNT {i} of {count}")
        print(f"{'='*60}")
        try:
            res = create_one_account(proxy=proxy)
            created_list.append(res)
            print(f"[CREATOR] Account {i} registered successfully: {res['user_id']}")
        except Exception as e:
            print(f"[CREATOR] ERROR creating account {i}: {e}")
            
        if i < count:
            print("[CREATOR] Sleeping 10 seconds before next creation...")
            time.sleep(10)
            
    return created_list
