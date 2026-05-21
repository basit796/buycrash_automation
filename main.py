"""
main.py
-------
Orchestrator for BuyCrash report automation.

Usage:
    python main.py                  # Run using start number from Google Sheet
    python main.py --reset          # Reset local progress
    python main.py --start 283746   # Override start number

Session mode: NO-LOGIN
    - Navigates directly to the search URL (no account login).
    - Rate-limit pauses and session refresh are handled in searcher.py.
    - Pause schedule: [3, 6, 15, 30, 60] min × 2 cycles → terminates.

Data is saved to:
  - Local Excel  (crash_reports.xlsx)
  - Google Sheets (Found / Not Found / Errors tabs)
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
    # 1. Local Excel — full data, our internal record
    save_found_report(record)
    # 2. Google Sheets — client fields only: Report Number # + DOI
    sheets_handler.save_found(
        report_number    = str(record.get("reportNumber", "")),
        date_of_incident = str(record.get("dateOfIncident", "")),
    )


def on_not_found(report_number: str):
    save_not_found_report(report_number)
    sheets_handler.save_not_found(report_number)


def on_error(report_number: str, error_msg: str):
    """Called after 3 retries all fail — saves to Errors sheet, NOT Not Found."""
    print(f"   [ERROR FINAL] {report_number}: {error_msg[:80]}")
    sheets_handler.save_error(report_number, error_msg)
    save_not_found_report(f"ERROR:{report_number}")


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
    print("  Mode: NO-LOGIN (direct URL, IP-agnostic)")
    print("=" * 60)

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

    print(f"\nTarget  : Find {TARGET_FOUND} valid reports")
    print(f"Starting: report number {current_report}\n")

    # ── NOTE: Account rotation is commented out (IP-based rate limiting) ──
    # accounts_info:
    # for i, acc in enumerate(ACCOUNTS):
    #     print(f"  Account {i+1}: {acc['username']}")

    while found_total < TARGET_FOUND:
        BATCH_SIZE = 10
        batch      = list(range(current_report, current_report + BATCH_SIZE))

        print(f"\n{'='*60}")
        print(f"  Batch  : {batch[0]} -> {batch[-1]}")
        print(f"  Found  : {found_total}/{TARGET_FOUND}")
        print(f"{'='*60}")

        try:
            found_in_batch = run_search_session(
                report_numbers     = batch,
                found_callback     = on_found,
                not_found_callback = on_not_found,
                found_so_far       = found_total,
                target             = TARGET_FOUND,
                no_login           = True,           # <── no browser login
                error_callback     = on_error,
                # ── Account params commented out (not used in no_login mode) ──
                # account    = ACCOUNTS[account_idx % len(ACCOUNTS)],
                # account_idx= account_idx % len(ACCOUNTS),
                # on_limit_hit = on_limit_hit,
            )
            found_total += found_in_batch
            current_report += BATCH_SIZE

        except Exception as e:
            err = str(e)
            if "LIMIT_EXHAUSTED" in err:
                print(f"\n[FATAL] {err}")
                print("[FATAL] Saving progress and terminating.")
                save_progress(current_report)
                break
            else:
                print(f"\n[ERROR] Batch error: {e}")
                print("Saving progress and retrying next batch...")
                current_report += BATCH_SIZE   # skip this batch on unknown error

        save_progress(current_report)
        print(f"\nProgress: {found_total}/{TARGET_FOUND} valid reports found")

        if found_total >= TARGET_FOUND:
            break

        # Brief pause between batches
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