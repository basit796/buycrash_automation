"""
mailreader.py
-------------
Mail.tm API client — creates accounts and reads OTP emails.

Mail.tm is a free disposable email service with a REST API.
No signup, no API key needed — just create an account via API.

API base: https://api.mail.tm
Docs    : https://docs.mail.tm
"""
import re
import time
import requests

MAILTM_API = "https://api.mail.tm"


# -------------------------------------------------------------------
# ACCOUNT CREATION
# -------------------------------------------------------------------

def get_available_domain() -> str:
    """Get the first available Mail.tm domain (e.g. 'mail.tm')."""
    resp = requests.get(f"{MAILTM_API}/domains", timeout=10)
    resp.raise_for_status()
    domains = resp.json().get("hydra:member", [])
    if not domains:
        raise Exception("No Mail.tm domains available")
    return domains[0]["domain"]


def create_account(username: str = None, password: str = "AutoPass123!") -> dict:
    """
    Create a new Mail.tm account.
    If username is None, generates a random one.
    Returns {"email": ..., "password": ..., "token": ...}
    """
    import random, string
    if not username:
        username = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))

    domain = get_available_domain()
    email  = f"{username}@{domain}"

    resp = requests.post(f"{MAILTM_API}/accounts", json={
        "address":  email,
        "password": password,
    }, timeout=10)

    if resp.status_code == 422:
        raise Exception(f"Account creation failed (address taken?): {resp.text}")
    resp.raise_for_status()

    token = get_token(email, password)
    return {"email": email, "password": password, "token": token}


def get_token(email: str, password: str) -> str:
    """Authenticate and return a JWT token."""
    resp = requests.post(f"{MAILTM_API}/token", json={
        "address":  email,
        "password": password,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()["token"]


# -------------------------------------------------------------------
# READ INBOX
# -------------------------------------------------------------------

def get_messages(token: str) -> list:
    """Return list of messages in the inbox."""
    resp = requests.get(f"{MAILTM_API}/messages", headers={
        "Authorization": f"Bearer {token}"
    }, timeout=10)
    resp.raise_for_status()
    return resp.json().get("hydra:member", [])


def get_message_body(token: str, message_id: str) -> str:
    """Return full text body of a specific message."""
    resp = requests.get(f"{MAILTM_API}/messages/{message_id}", headers={
        "Authorization": f"Bearer {token}"
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    # Prefer plain text, fall back to HTML stripped
    text = data.get("text", "") or ""
    if not text:
        html = data.get("html", [""])[0] if data.get("html") else ""
        text = re.sub(r"<[^>]+>", " ", html)
    return text


def extract_otp(text: str) -> str:
    """
    Extract OTP from email body.
    Tries common patterns:
      - 4-8 digit standalone number
      - "code: 123456", "OTP: 123456", "passcode: 123456"
    """
    # Pattern 1: labeled code
    labeled = re.search(
        r'(?:code|otp|passcode|verification)[^\d]{0,10}(\d{4,8})',
        text, re.IGNORECASE
    )
    if labeled:
        return labeled.group(1)

    # Pattern 2: standalone 4-8 digit number on its own line or surrounded by spaces
    standalone = re.findall(r'(?<!\d)(\d{4,8})(?!\d)', text)
    if standalone:
        # Return the first one that looks like an OTP (not a year or zip code)
        for candidate in standalone:
            if not (1900 <= int(candidate) <= 2100):   # exclude years
                return candidate

    return None


# -------------------------------------------------------------------
# POLL FOR OTP  (main function used by searcher.py)
# -------------------------------------------------------------------

def wait_for_otp(token: str,
                 max_wait_sec: int = 120,
                 poll_interval: int = 8,
                 seen_ids: set = None) -> str:
    """
    Poll the Mail.tm inbox until a new message arrives containing an OTP.
    Returns the OTP string, or None if timed out.

    seen_ids: set of message IDs already processed — pass in to avoid
              re-reading old messages.
    """
    if seen_ids is None:
        seen_ids = set()

    elapsed = 0
    print(f"   [MAIL.TM] Polling inbox for OTP (max {max_wait_sec}s)...")

    while elapsed < max_wait_sec:
        try:
            messages = get_messages(token)
            for msg in messages:
                mid = msg.get("id", "")
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)

                subject = msg.get("subject", "")
                print(f"   [MAIL.TM] New email: '{subject}'")

                body = get_message_body(token, mid)
                otp  = extract_otp(body)
                if otp:
                    print(f"   [MAIL.TM] OTP extracted: {otp}")
                    return otp
                else:
                    print(f"   [MAIL.TM] No OTP found in this email — waiting...")

        except Exception as e:
            print(f"   [MAIL.TM] Poll error: {e}")

        time.sleep(poll_interval)
        elapsed += poll_interval
        print(f"   [MAIL.TM] Waiting for OTP... {elapsed}s / {max_wait_sec}s")

    print(f"   [MAIL.TM] Timeout — no OTP received after {max_wait_sec}s")
    return None


def get_inbox_snapshot(token: str) -> set:
    """Return set of current message IDs — call before triggering OTP send."""
    try:
        return {m["id"] for m in get_messages(token)}
    except Exception:
        return set()