"""
main.py
-------
Orchestrator for BuyCrash report automation.

Usage:
    python main.py                  # Run using start number from Google Sheet
    python main.py --reset          # Reset local progress
    python main.py --start 283746   # Override start number

Session mode: SINGLE ACCOUNT LOGIN
    - Logs in once via browser; reuses session cookies.
    - Batch size: 20 reports per batch.
    - 20-minute pause between every batch.
    - On SEARCH_LIMIT_REACHED: pauses 10 min and retries — forever, never terminates.
    - Random 15–35s delay between individual report searches.

Data is saved to:
  - Local Excel  (crash_reports.xlsx)
  - Google Sheets (Found / Not Found / Errors tabs)
"""
import argparse
import time
from config import TARGET_FOUND, START_REPORT, USERNAME
from progress import load_progress, save_progress, reset_progress
from excel_handler import save_found_report, save_not_found_report, get_summary
from searcher import run_search_session
import sheets_handler

# Batch size — number of reports searched before a 20-min pause
BATCH_SIZE = 20


# -------------------------------------------------------------------
# Callbacks — dual-save to local Excel AND Google Sheets
# -------------------------------------------------------------------

def on_found(record: dict):
    # 1. Local Excel — full data
    save_found_report(record)
    # 2. Google Sheets — Report Number + DOI only
    sheets_handler.save_found(
        report_number    = str(record.get("reportNumber", "")),
        date_of_incident = str(record.get("dateOfIncident", "")),
    )


def on_not_found(report_number: str):
    save_not_found_report(report_number)
    sheets_handler.save_not_found(report_number)


def on_error(report_number: str, error_msg: str):
    """Called after 3 retries all fail — saves to Errors sheet."""
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
    print("  BuyCrash Report Automation")
    print("  Mode: SINGLE ACCOUNT LOGIN")
    print(f"  Account : {USERNAME}")
    print(f"  Batch   : {BATCH_SIZE} reports per batch")
    print(f"  Pause   : 20 min between batches")
    print(f"  Delay   : 15–35s random between each search")
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
    batch_num   = 0

    print(f"\nTarget  : Find {TARGET_FOUND} valid reports")
    print(f"Starting: report number {current_report}\n")

    while found_total < TARGET_FOUND:
        batch_num += 1
        batch      = list(range(current_report, current_report + BATCH_SIZE))

        print(f"\n{'='*60}")
        print(f"  Batch #{batch_num:03d}  :  {batch[0]} → {batch[-1]}")
        print(f"  Found so far : {found_total}/{TARGET_FOUND}")
        print(f"{'='*60}")

        try:
            found_in_batch = run_search_session(
                report_numbers     = batch,
                found_callback     = on_found,
                not_found_callback = on_not_found,
                found_so_far       = found_total,
                target             = TARGET_FOUND,
                error_callback     = on_error,
            )
            found_total    += found_in_batch
            current_report += BATCH_SIZE

        except Exception as e:
            err = str(e)
            print(f"\n[ERROR] Unexpected batch error: {e}")
            print("Saving progress and continuing to next batch...")
            current_report += BATCH_SIZE   # skip broken batch

        save_progress(current_report)
        print(f"\nProgress saved: {found_total}/{TARGET_FOUND} valid reports found")

        if found_total >= TARGET_FOUND:
            break

        # 20-minute pause between batches (skipped after the final batch)
        _between_batch_pause(batch_num)

    # Final summary
    print("\n" + "=" * 60)
    print(f"DONE! Found {found_total} valid reports.")
    get_summary()
    print(f"\nLocal results : crash_reports.xlsx")
    print(f"Cloud results : Google Sheets")
    print("=" * 60)


def _between_batch_pause(batch_num: int):
    """20-minute countdown pause between batches."""
    wait_sec = 20 * 60
    print(f"\n{'='*60}")
    print(f"  [BATCH PAUSE] Batch #{batch_num:03d} done. Waiting 20 min...")
    print(f"{'='*60}")
    for remaining in range(wait_sec, 0, -30):
        mins, secs = divmod(remaining, 60)
        print(f"   [BATCH PAUSE] Next batch in {mins}m {secs:02d}s...  ", end="\r")
        time.sleep(30)
    print()
    print(f"   [BATCH PAUSE] Starting batch #{batch_num + 1:03d} now.\n")


if __name__ == "__main__":
    main()