"""
setup_accounts.py
-----------------
ONE-TIME HELPER SCRIPT — run this before deploying the main automation.

What it does:
  1. Creates 3 Mail.tm email accounts (one per site account)
  2. Prints the email + token for each
  3. You then: register on buycrash.lexisnexisrisk.com using those emails
  4. Script waits and auto-reads the OTP from Mail.tm inbox
  5. You complete registration, then move to next account

After running this script, fill the Google Sheet Config tab:
  B1   Account1 Username  ← the mail.tm email from this script
  B2   Account1 Password  ← your chosen password for the site account
  B3   Account2 Username
  B4   Account2 Password
  B5   Account3 Username
  B6   Account3 Password
  B19  Account1 Mail.tm Token  ← token printed by this script
  B20  Account2 Mail.tm Token
  B21  Account3 Mail.tm Token

Usage:
  python setup_accounts.py
  python setup_accounts.py --accounts 3   (default)
  python setup_accounts.py --accounts 1   (just one account)
"""
import argparse
import time
from mailreader import create_account, wait_for_otp, get_inbox_snapshot


def setup_one_account(account_num: int) -> dict:
    print(f"\n{'='*55}")
    print(f"  Setting up Account {account_num}")
    print(f"{'='*55}")

    # Create Mail.tm account
    print(f"\nStep 1 — Creating Mail.tm email address...")
    acc = create_account()
    print(f"\n  [OK] Mail.tm email : {acc['email']}")
    print(f"  [OK] Mail.tm token : {acc['token']}")
    print(f"\n  Save these — you'll need them for the Config sheet.")

    # Snapshot current inbox so we only catch NEW emails
    seen_ids = get_inbox_snapshot(acc["token"])

    # Prompt user to register
    print(f"\nStep 2 — Register on the site using this email:")
    print(f"  https://buycrash.lexisnexisrisk.com")
    print(f"  Use email   : {acc['email']}")
    print(f"  Choose any password for the site account")
    print(f"\n  After clicking 'Register' / 'Submit', come back here.")
    input(f"\n  Press ENTER when you have submitted the registration form...")

    # Poll for OTP
    print(f"\nStep 3 — Waiting for OTP email...")
    otp = wait_for_otp(
        token          = acc["token"],
        max_wait_sec   = 300,   # 5 min
        poll_interval  = 8,
        seen_ids       = seen_ids,
    )

    if otp:
        print(f"\n  [OK] OTP received: {otp}")
        print(f"  Enter this OTP on the site to complete registration.")
        input(f"\n  Press ENTER after you have completed registration on the site...")
    else:
        print(f"\n  [--] No OTP received -- check if registration email went to spam")
        print(f"    or try re-sending the verification email on the site.")

    return {
        "account_num":   account_num,
        "mailtm_email":  acc["email"],
        "mailtm_token":  acc["token"],
        "otp_received":  otp or "NONE",
    }


def main():
    parser = argparse.ArgumentParser(description="Setup Mail.tm accounts for BuyCrash")
    parser.add_argument("--accounts", type=int, default=9,
                        help="Number of accounts to set up (default: 9)")
    args = parser.parse_args()

    print("=" * 55)
    print("  BuyCrash Account Setup -- Mail.tm Helper")
    print("=" * 55)
    print(f"\nThis will create {args.accounts} Mail.tm email address(es)")
    print("and guide you through registering them on the site.")
    print("Cells to fill in Google Sheet Config tab:")
    for n in range(1, args.accounts + 1):
        row_user  = 1 + (n - 1) * 2
        row_email = 26 + (n - 1) * 2 + 1
        row_token = row_email + 1
        print(f"  Account {n}: B{row_user}/{row_user+1} (user/pass)  "
              f"B{row_email}/{row_token} (mailtm email/token)")
    print()

    results = []
    for i in range(1, args.accounts + 1):
        result = setup_one_account(i)
        results.append(result)
        if i < args.accounts:
            print(f"\n  Moving to account {i+1} in 3 seconds...")
            time.sleep(3)

    # Final summary
    print(f"\n\n{'='*55}")
    print(f"  SETUP COMPLETE — Copy these into your Config sheet")
    print(f"{'='*55}\n")

    for r in results:
        n = r["account_num"]
        row_user  = 1 + (n - 1) * 2     # B1, B3, B5, ..., B17
        row_pass  = row_user + 1          # B2, B4, B6, ..., B18
        row_email = 26 + (n - 1) * 2 + 1 # B27, B29, B31, ..., B43
        row_token = row_email + 1         # B28, B30, B32, ..., B44
        print(f"  Account {n}:")
        print(f"    B{row_user}  (Username)     : {r['mailtm_email']}")
        print(f"    B{row_pass}  (Password)     : <the password you chose on the site>")
        print(f"    B{row_email} (Mail.tm Email) : {r['mailtm_email']}")
        print(f"    B{row_token} (Mail.tm Token) : {r['mailtm_token']}")
        print()

    print("  Done! Run main.py (or POST /start) to begin automation.")


if __name__ == "__main__":
    main()