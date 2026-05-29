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
    "Nicholas", "Eric", "Jonathan", "Stephen", "Larry", "Justin", "Scott", "Brandon", "Benjamin", "Samuel",
    "Frank", "Gregory", "Raymond", "Alexander", "Patrick", "Jack", "Dennis", "Jerry", "Tyler", "Aaron",
    "Jose", "Adam", "Nathan", "Henry", "Douglas", "Zachary", "Peter", "Kyle", "Walter", "Ethan",
    "Jeremy", "Harold", "Carl", "Keith", "Roger", "Gerald", "Christian", "Terry", "Sean", "Arthur",
    "Austin", "Noah", "Jesse", "Joe", "Bryan", "Billy", "Jordan", "Albert", "Dylan", "Bruce",
    "Willie", "Gabriel", "Alan", "Juan", "Logan", "Wayne", "Ralph", "Roy", "Eugene", "Randy"
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
    "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
    "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts",
    "Gomez", "Phillips", "Evans", "Diaz", "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart",
    "Morris", "Morales", "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper", "Peterson",
    "Bailey", "Reed", "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward", "Richardson", "Watson",
    "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray", "Mendoza", "Ruiz", "Hughes", "Price"
]

# Real Michigan (Detroit Area) Addresses Dataset

ADDRESSES = [
    {"street": "1001 Woodward Ave", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "150 W Jefferson Ave", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "500 Griswold St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "645 Griswold St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "660 Woodward Ave", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "211 W Fort St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "400 Monroe St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "555 E Lafayette St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "1200 Washington Blvd", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "230 E Grand River Ave", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "1407 Randolph St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "350 Madison St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "25 Peterboro St", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "71 Garfield St", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "441 W Canfield St", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "15 E Kirby St", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "5200 Woodward Ave", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "4600 Cass Ave", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "5901 Cass Ave", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "440 Burroughs St", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "11000 W McNichols Rd", "city": "Detroit", "state": "MI", "zip": "48221"},
    {"street": "2250 E Grand Blvd", "city": "Detroit", "state": "MI", "zip": "48211"},
    {"street": "1421 Lafayette Blvd", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "834 Woodward Ave", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "3400 E Jefferson Ave", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "7310 W Vernor Hwy", "city": "Detroit", "state": "MI", "zip": "48209"},
    {"street": "19701 W 7 Mile Rd", "city": "Detroit", "state": "MI", "zip": "48219"},
    {"street": "14600 Fenkell Ave", "city": "Detroit", "state": "MI", "zip": "48227"},
    {"street": "4201 W Davison St", "city": "Detroit", "state": "MI", "zip": "48238"},
    {"street": "8100 E Jefferson Ave", "city": "Detroit", "state": "MI", "zip": "48214"},
    {"street": "2934 Rosa Parks Blvd", "city": "Detroit", "state": "MI", "zip": "48216"},
    {"street": "16101 Harper Ave", "city": "Detroit", "state": "MI", "zip": "48224"},
    {"street": "6101 Tireman Ave", "city": "Detroit", "state": "MI", "zip": "48204"},
    {"street": "21000 Mack Ave", "city": "Grosse Pointe Woods", "state": "MI", "zip": "48236"},
    {"street": "3100 Gratiot Ave", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "10200 W Outer Dr", "city": "Detroit", "state": "MI", "zip": "48223"},
    {"street": "1150 Griswold St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "2211 Woodward Ave", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "1 Campus Martius", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "500 Temple St", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "3663 Woodward Ave", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "3011 W Grand Blvd", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "461 Piquette Ave", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "600 Renaissance Center", "city": "Detroit", "state": "MI", "zip": "48243"},
    {"street": "2000 Brush St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "50 W Montcalm St", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "2901 Grand River Ave", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "1845 E Warren Ave", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "607 Shelby St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "719 Griswold St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "440 Alfred St", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "1435 Randolph St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "65 Cadillac Sq", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "1274 Library St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "1509 Broadway St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "100 Temple St", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "3500 Russell St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "Eastern Market Shed 5", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "2131 Beaufait St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "8000 Kercheval Ave", "city": "Detroit", "state": "MI", "zip": "48214"},
    {"street": "9600 Gratiot Ave", "city": "Detroit", "state": "MI", "zip": "48213"},
    {"street": "1145 Griswold St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "1000 Beaubien Blvd", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "2799 W Grand Blvd", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "6000 Woodward Ave", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "1528 Woodward Ave", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "100 Erskine St", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "511 W Canfield St", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "6640 E Jefferson Ave", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "630 Merrick St", "city": "Detroit", "state": "MI", "zip": "48208"},
    {"street": "4731 Grand River Ave", "city": "Detroit", "state": "MI", "zip": "48208"},
    {"street": "6053 Chase Rd", "city": "Dearborn", "state": "MI", "zip": "48126"},
    {"street": "13624 Michigan Ave", "city": "Dearborn", "state": "MI", "zip": "48126"},
    {"street": "4901 Evergreen Rd", "city": "Dearborn", "state": "MI", "zip": "48128"},
    {"street": "16031 W McNichols Rd", "city": "Detroit", "state": "MI", "zip": "48235"},
    {"street": "17340 Lahser Rd", "city": "Detroit", "state": "MI", "zip": "48219"},
    {"street": "17180 Livernois Ave", "city": "Detroit", "state": "MI", "zip": "48221"},
    {"street": "1254 Library St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "415 Clifford St", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "100 Marquette Dr", "city": "Detroit", "state": "MI", "zip": "48214"},
    {"street": "8220 Second Ave", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "5401 Woodward Ave", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "4707 St Antoine St", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "1301 W Lafayette Blvd", "city": "Detroit", "state": "MI", "zip": "48226"},
    {"street": "9850 Grand River Ave", "city": "Detroit", "state": "MI", "zip": "48204"},
    {"street": "18100 Meyers Rd", "city": "Detroit", "state": "MI", "zip": "48235"},
    {"street": "1331 Holden St", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "3031 W Grand Blvd", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "4400 John R St", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "2990 W Grand Blvd", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "1355 Atwater St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "1340 E Atwater St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "200 Walker St", "city": "Detroit", "state": "MI", "zip": "48207"},
    {"street": "7430 2nd Ave", "city": "Detroit", "state": "MI", "zip": "48202"},
    {"street": "71 W Warren Ave", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "474 Peterboro St", "city": "Detroit", "state": "MI", "zip": "48201"},
    {"street": "1040 Woodward Ave", "city": "Detroit", "state": "MI", "zip": "48226"}
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
    "Platinum77&y", "Titanium88*z", "Rocket12@A", "Shadow34#B", "Thunder56$C",
    "Lightning78%D", "Phoenix90^E", "Dragon21&F", "Tiger43*G", "Wolf65!H",
    "Falcon87@J", "Viper19#K", "Panther31$L", "Ranger53%M", "Knight75^N",
    "Samurai97&O", "Ninja28*P", "Hunter49!Q", "Spartan61@R", "Blaze83#S",
    "Storm05$T", "Matrix27%U", "Quantum48^V", "Neptune69&W", "Mercury80*X",
    "Saturn14!Y", "Jupiter36@Z", "Cosmos58#a", "Orbit79$b", "Galaxy91%c",
    "Comet13^d", "Astro35&e", "Meteor57*f", "Rocket99!g", "Fusion22@h"
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

def generate_user_id(email: str, first_name: str, last_name: str) -> str:
    """
    User ID Format:
    first_name + last_name + 4 chars from email

    Max length: 20
    """

    # Clean values
    first = re.sub(r"[^a-zA-Z0-9]", "", first_name)
    last = re.sub(r"[^a-zA-Z0-9]", "", last_name)

    # Always keep 4 chars from email
    email_prefix = email.split("@")[0]
    email_part = re.sub(r"[^a-zA-Z0-9]", "", email_prefix)[:4]

    # Reserve 4 chars for email part
    remaining_length = 20 - len(email_part)

    # Combine and trim names only
    name_part = (first + last)[:remaining_length]

    # Final user_id
    user_id = name_part + email_part

    # Ensure starts with letter
    if not user_id[0].isalpha():
        user_id = "a" + user_id

    # Final hard limit
    user_id = user_id[:20]

    # Ensure minimum length
    if len(user_id) < 7:
        user_id = (user_id + "1234567")[:7]

    return user_id


def create_one_account(proxy: str = None, _retry: bool = False) -> dict:
    """
    Performs the full Mail.tm creation + BuyCrash registration + OTP submission.
    Retries from scratch once if registration fails.
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
    print(f"[CREATOR] Generated email password: {email_pass}")
    
    user_id = generate_user_id(email, first_name, last_name)
    print(f"[CREATOR] Generated User ID: {user_id}")
    
    # 3. SeleniumBase registration
    registration_url = "https://buycrash.lexisnexisrisk.com/ui/auth/registration"
    
    sb_proxy = None
    if proxy:
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

        # --- Step 2: The long registration form ---
        print("[CREATOR] Processing the long registration form...")

        sb.cdp.click("#firstName"); sb.sleep(0.2); sb.cdp.type("#firstName", first_name)
        sb.cdp.click("#lastName"); sb.sleep(0.2); sb.cdp.type("#lastName", last_name)
        sb.cdp.click("#phone"); sb.sleep(0.2); sb.cdp.type("#phone", phone)
        sb.cdp.click("#streetAddress1"); sb.sleep(0.2); sb.cdp.type("#streetAddress1", address["street"])
        sb.cdp.click("#city"); sb.sleep(0.2); sb.cdp.type("#city", address["city"])

        # State - Angular Material mat-select
        try:
            state_index = STATE_INDEX.get(address["state"], 22)
            sb.cdp.click("mat-select#state")
            sb.sleep(1)
            sb.cdp.evaluate(f"""
                (function() {{
                    var options = document.querySelectorAll('mat-option');
                    if (options.length >= {state_index}) {{
                        options[{state_index} - 1].click();
                    }}
                }})();
            """)
            sb.sleep(0.5)
            print(f"[CREATOR] State selected: {address['state']} (mat-option index {state_index})")
        except Exception as e:
            print(f"[CREATOR] State error: {e}")

        sb.cdp.click("#zipCode"); sb.sleep(0.2); sb.cdp.type("#zipCode", address["zip"])
        sb.cdp.click("#loginId"); sb.sleep(0.2); sb.cdp.type("#loginId", user_id)
        sb.cdp.click("#password"); sb.sleep(0.2); sb.cdp.type("#password", portal_pass)
        sb.cdp.click("#passwordConfirm"); sb.sleep(0.2); sb.cdp.type("#passwordConfirm", portal_pass)

        try:
            sb.cdp.click("#mat-radio-4-input")
            print("[CREATOR] OTP email Default radio selected")
        except Exception as e:
            print(f"[CREATOR] OTP radio error: {e}")
        
        sb.sleep(0.3)

        try:
            sb.cdp.click("#mat-mdc-checkbox-0-input")
            print("[CREATOR] Terms checkbox checked")
        except Exception as e:
            print(f"[CREATOR] Checkbox error: {e}")

        sb.sleep(0.5)
        sb.cdp.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        sb.sleep(1)

        sb.cdp.evaluate("""
            (function() {
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    if (btns[i].textContent.trim() === 'Continue Registration') {
                        btns[i].scrollIntoView();
                        btns[i].click();
                        return;
                    }
                }
            })();
        """)
        print("[CREATOR] Continue Registration clicked")

        print("[CREATOR] Form submitted. Waiting for OTP page to load...")
        sb.sleep(6)

        # --- Step 3: Fetch OTP and verify ---
        sb.save_screenshot("creator_before_otp_poll.png")
        print("[CREATOR] Screenshot saved — check creator_before_otp_poll.png")

        print("[CREATOR] Polling Mail.tm for 6-digit OTP...")
        otp = mailreader.wait_for_otp(token=mailtm_token, max_wait_sec=120)
        
        if not otp:
            print("[CREATOR] ERROR: Did not receive OTP email.")
            sb.save_screenshot("creator_error_no_otp.png")
            raise Exception("OTP timeout — verification failed")
            
        print(f"[CREATOR] Got OTP passcode: {otp}")
        
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

        current_url = sb.cdp.get_current_url()
        print(f"[CREATOR] Post-OTP URL: {current_url}")
        
        if "ui/report/search" not in current_url:
            sb.save_screenshot("creator_error_failed.png")
            if _retry:
                raise Exception(f"Registration failed after retry. Final URL: {current_url}")
            else:
                print("[CREATOR] Registration failed — retrying from scratch with new email...")
                return create_one_account(proxy=proxy, _retry=True)

        print("[CREATOR] Registration succeeded!")
        
        # 4. Save to Sheets
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