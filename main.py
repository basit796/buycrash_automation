"""
main.py
-------
Orchestrator for BuyCrash report automation.

Usage:
    python main.py                  # Run using start number from Google Sheet
    python main.py --reset          # Reset local progress
    python main.py --start 283746   # Override start number

Account rotation:
    - Rotates to the next account on every batch boundary
    - Rotates immediately when SEARCH_LIMIT_REACHED

Data is saved to:
  - Local Excel  (crash_reports.xlsx)
  - Google Sheets (Found / Not Found tabs)
"""
import argparse
import time
from config import TARGET_FOUND, START_REPORT, ACCOUNTS
from progress import load_progress, save_progress, reset_progress
from excel_handler import save_found_report, save_not_found_report, get_summary
from searcher import run_search_session
import sheets_handler


# -------------------------------------------------------------------
# Callbacks — dual-save to local Excel AND Google Sheets
# -------------------------------------------------------------------

def on_found(record: dict):
    save_found_report(record)
    sheets_handler.save_found(
        report_number    = str(record.get("reportNumber", "")),
        date_of_incident = str(record.get("dateOfIncident", "")),
    )


def on_not_found(report_number: str):
    save_not_found_report(report_number)
    sheets_handler.save_not_found(report_number)


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="BuyCrash Report Automation")
    parser.add_argument("--reset", action="store_true", help="Reset local progress")
    parser.add_argument("--start", type=int, help="Override start report number")
    args = parser.parse_args()

    print("=" * 60)
    print("  BuyCrash Report Automation  (+ Google Sheets)")
    print("=" * 60)

    if not ACCOUNTS:
        print("FATAL: No accounts found in .env (need SITE_USERNAME_1 / PASSWORD_B64_1)")
        return

    print(f"\nAccounts loaded: {len(ACCOUNTS)}")
    for i, acc in enumerate(ACCOUNTS):
        print(f"  Account {i+1}: {acc['username']}")

    # Test Google Sheets
    print("\nChecking Google Sheets connection...")
    if not sheets_handler.test_connection():
        print("Google Sheets unavailable — saving to local Excel only")
    print()

    if args.reset:
        reset_progress()

    # Determine starting report number
    if args.start:
        current_report = args.start
        print(f"Starting from CLI argument: {current_report}")
    else:
        gs_start = sheets_handler.get_start_number()
        if gs_start and gs_start > 0:
            current_report = gs_start
            print(f"Starting from Google Sheet 'Start Number': {current_report}")
        else:
            current_report = load_progress()
            print(f"Starting from local progress file: {current_report}")

    found_total = 0
    account_idx = 0      # global ever-incrementing index (mod len gives actual slot)
    limit_hit   = False  # flag set by on_limit_hit callback

    print(f"\nTarget  : Find {TARGET_FOUND} valid reports")
    print(f"Starting: report number {current_report}")
    print(f"Accounts: {len(ACCOUNTS)} available (rotate per batch + on rate limit)\n")

    while found_total < TARGET_FOUND:
        BATCH_SIZE   = 10
        batch        = list(range(current_report, current_report + BATCH_SIZE))
        real_idx     = account_idx % len(ACCOUNTS)
        account      = ACCOUNTS[real_idx]

        print(f"\n{'='*60}")
        print(f"  Batch  : {batch[0]} -> {batch[-1]}")
        print(f"  Account: {real_idx + 1} / {len(ACCOUNTS)}  ({account['username']})")
        print(f"  Found  : {found_total}/{TARGET_FOUND}")
        print(f"{'='*60}")

        limit_hit = False

        def on_limit_hit():
            nonlocal limit_hit
            limit_hit = True

        try:
            found_in_batch = run_search_session(
                report_numbers     = batch,
                found_callback     = on_found,
                not_found_callback = on_not_found,
                found_so_far       = found_total,
                target             = TARGET_FOUND,
                account            = account,
                account_idx        = real_idx,
                on_limit_hit       = on_limit_hit,
            )
            found_total += found_in_batch

        except Exception as e:
            print(f"\nSession error: {e}")
            print("Saving progress and continuing with next account...")

        # If limit was hit mid-batch: DON'T advance report number
        # so the same range is retried with the next account
        if not limit_hit:
            current_report += BATCH_SIZE

        save_progress(current_report)
        print(f"\nProgress: {found_total}/{TARGET_FOUND} valid reports found")

        if found_total >= TARGET_FOUND:
            break

        # Rotate account
        next_real = (account_idx + 1) % len(ACCOUNTS)
        if limit_hit:
            print(f"[ROTATE] Rate limit hit — switching "
                  f"account {real_idx+1} -> {next_real+1} "
                  f"({ACCOUNTS[next_real]['username']}), retrying same batch")
        else:
            print(f"[ROTATE] Batch done — switching "
                  f"account {real_idx+1} -> {next_real+1} "
                  f"({ACCOUNTS[next_real]['username']})")

        account_idx += 1
        time.sleep(3)

    # Final summary
    print("\n" + "=" * 60)
    print(f"DONE! Found {found_total} valid reports.")
    get_summary()
    print(f"\nLocal results : crash_reports.xlsx")
    print(f"Cloud results : Google Sheets")
    print("=" * 60)


if __name__ == "__main__":
    main()