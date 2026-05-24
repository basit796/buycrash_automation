"""
account_creator.py
------------------
Automates account creation on buycrash.lexisnexisrisk.com using SeleniumBase CDP mode and Mail.tm disposable emails.
Loads USA billing address pools, name pools, and password pools. Logs registered accounts directly to the "Credentials" Google Sheet.
"""
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

    with SB(uc=True, test=False, locale="en", headless=True, proxy=sb_proxy) as sb:
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
        
        # --- Step 2: The long registration page ---
        print("[CREATOR] Processing the long registration form...")
        
        # Check radio button again if needed
        try:
            sb.cdp.evaluate('document.querySelector("input[id=\'involvedParty\']").click();')
        except Exception:
            pass
            
        # First Name
        first_filled = False
        for sel in ["input[name='firstName']", "input[id='firstName']"]:
            try:
                sb.cdp.click(sel); sb.sleep(0.2); sb.cdp.type(sel, first_name)
                first_filled = True; break
            except Exception:
                continue
        if not first_filled:
            sb.cdp.evaluate(f'document.querySelector("input[name=\'firstName\']").value = "{first_name}";')

        # Last Name
        last_filled = False
        for sel in ["input[name='lastName']", "input[id='lastName']"]:
            try:
                sb.cdp.click(sel); sb.sleep(0.2); sb.cdp.type(sel, last_name)
                last_filled = True; break
            except Exception:
                continue
        if not last_filled:
            sb.cdp.evaluate(f'document.querySelector("input[name=\'lastName\']").value = "{last_name}";')

        # Phone Number
        phone_filled = False
        for sel in ["input[name='phoneNumber']", "input[name='phone']", "input[id='phone']"]:
            try:
                sb.cdp.click(sel); sb.sleep(0.2); sb.cdp.type(sel, phone)
                phone_filled = True; break
            except Exception:
                continue
        if not phone_filled:
            sb.cdp.evaluate(f'document.querySelector("input[name=\'phoneNumber\']").value = "{phone}";')

        # Street Address
        addr_filled = False
        for sel in ["input[name='streetAddress1']", "input[name='addressLine1']", "input[id='streetAddress1']"]:
            try:
                sb.cdp.click(sel); sb.sleep(0.2); sb.cdp.type(sel, address["street"])
                addr_filled = True; break
            except Exception:
                continue
        if not addr_filled:
            sb.cdp.evaluate(f'document.querySelector("input[name=\'streetAddress1\']").value = "{address["street"]}";')

        # City
        city_filled = False
        for sel in ["input[name='city']", "input[id='city']"]:
            try:
                sb.cdp.click(sel); sb.sleep(0.2); sb.cdp.type(sel, address["city"])
                city_filled = True; break
            except Exception:
                continue
        if not city_filled:
            sb.cdp.evaluate(f'document.querySelector("input[name=\'city\']").value = "{address["city"]}";')

        # State dropdown
        state_filled = False
        for sel in ["select[name='state']", "select[id='state']"]:
            try:
                sb.cdp.click(sel)
                sb.sleep(0.5)
                sb.cdp.press_keys(sel, address["state"])
                sb.sleep(0.5)
                sb.cdp.press_keys(sel, "\n")
                state_filled = True; break
            except Exception:
                continue
        if not state_filled:
            try:
                sb.cdp.evaluate(f"""
                    (function() {{
                        var select = document.querySelector("select[name='state']") || document.querySelector("select[id='state']");
                        if (select) {{
                            select.value = "{address["state"]}";
                            select.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        }}
                    }})();
                """)
            except Exception:
                pass

        # Zip
        zip_filled = False
        for sel in ["input[name='zip']", "input[name='zipCode']", "input[id='zip']"]:
            try:
                sb.cdp.click(sel); sb.sleep(0.2); sb.cdp.type(sel, address["zip"])
                zip_filled = True; break
            except Exception:
                continue
        if not zip_filled:
            sb.cdp.evaluate(f'document.querySelector("input[name=\'zip\']").value = "{address["zip"]}";')

        # Portal User ID
        user_filled = False
        for sel in ["input[name='userId']", "input[name='username']", "input[id='userId']"]:
            try:
                sb.cdp.click(sel); sb.sleep(0.2); sb.cdp.type(sel, user_id)
                user_filled = True; break
            except Exception:
                continue
        if not user_filled:
            sb.cdp.evaluate(f'document.querySelector("input[name=\'userId\']").value = "{user_id}";')

        # Portal Password
        pass_filled = False
        for sel in ["input[name='password']", "input[type='password'][id*='password']"]:
            try:
                sb.cdp.click(sel); sb.sleep(0.2); sb.cdp.type(sel, portal_pass)
                pass_filled = True; break
            except Exception:
                continue
        if not pass_filled:
            sb.cdp.evaluate(f'document.querySelector("input[name=\'password\']").value = "{portal_pass}";')

        # Confirm Portal Password
        confirm_filled = False
        for sel in ["input[name='reenterPassword']", "input[name='confirmPassword']", "input[type='password'][id*='confirm']"]:
            try:
                sb.cdp.click(sel); sb.sleep(0.2); sb.cdp.type(sel, portal_pass)
                confirm_filled = True; break
            except Exception:
                continue
        if not confirm_filled:
            try:
                sb.cdp.evaluate(f"""
                    var pw = document.querySelectorAll("input[type='password']");
                    if (pw.length > 1) {{
                        pw[1].value = "{portal_pass}";
                    }}
                """)
            except Exception:
                pass

        # Email OTP Radio "Default" click
        otp_radio_clicked = False
        for sel in ["input[type='radio'][name='emailDefault']", "input[type='radio'][value='email']", "label:contains('Default')"]:
            try:
                sb.cdp.click(sel)
                otp_radio_clicked = True
                break
            except Exception:
                continue
        if not otp_radio_clicked:
            try:
                sb.cdp.evaluate("""
                    (function() {
                        var radios = document.querySelectorAll("input[type='radio']");
                        for (var i = 0; i < radios.length; i++) {
                            var name = radios[i].getAttribute('name') || '';
                            if (name.toLowerCase().includes('email')) {
                                radios[i].click();
                                break;
                            }
                        }
                    })();
                """)
            except Exception:
                pass

        # Check terms and conditions box
        terms_checked = False
        for sel in ["input[type='checkbox']", "input[name='terms']", "label:contains('agree')", "label:contains('Terms of Use')"]:
            try:
                sb.cdp.click(sel)
                terms_checked = True
                break
            except Exception:
                continue
        if not terms_checked:
            try:
                sb.cdp.evaluate('document.querySelector("input[type=\'checkbox\']").click();')
            except Exception:
                pass

        # Submit long form
        form_submitted = False
        for sel in ["button:contains('Continue Registration')", "input[value='Continue Registration']", "button[type='submit']"]:
            try:
                sb.cdp.click(sel)
                form_submitted = True
                break
            except Exception:
                continue
        if not form_submitted:
            try:
                sb.cdp.evaluate('document.querySelector("button[type=\'submit\']").click();')
            except Exception:
                pass

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
