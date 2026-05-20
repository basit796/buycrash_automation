"""
main.py
-------
Orchestrator for BuyCrash report automation.

Usage:
    python main.py                  # Run using start number from Google Sheet
    python main.py --reset          # Reset local progress, still reads GSheet start
    python main.py --start 283746   # Override start number from command line

Data is saved to:
  - Local Excel  (crash_reports.xlsx)
  - Google Sheets (Found / Not Found tabs)
"""
import argparse
import time
from config import TARGET_FOUND, START_REPORT
from progress import load_progress, save_progress, reset_progress
from excel_handler import save_found_report, save_not_found_report, get_summary
from searcher import run_search_session
import sheets_handler


# -------------------------------------------------------------------
# Callbacks — dual-save to local Excel AND Google Sheets
# -------------------------------------------------------------------

def on_found(record: dict):
    """Called for each successfully found report."""
    # 1. Save to local Excel
    save_found_report(record)

    # 2. Save to Google Sheets: Report Number + DOI only
    sheets_handler.save_found(
        report_number    = str(record.get("reportNumber", "")),
        date_of_incident = str(record.get("dateOfIncident", "")),
    )


def on_not_found(report_number: str):
    """Called for each report that was not found."""
    # 1. Save to local Excel
    save_not_found_report(report_number)

    # 2. Save to Google Sheets: Report Number + Date Searched
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

    # Test Google Sheets connection before we start
    print("\n🔗 Checking Google Sheets connection...")
    if not sheets_handler.test_connection():
        print("⚠️  Google Sheets unavailable — results will be saved to local Excel only")
    print()

    # Handle reset
    if args.reset:
        reset_progress()

    # ── Determine starting report number ────────────────────────────
    if args.start:
        # Explicit override from CLI
        current_report = args.start
        print(f"📌 Starting from CLI argument: {current_report}")

    else:
        # Priority 1: Google Sheet "Start Number" tab (cell A2)
        gs_start = sheets_handler.get_start_number()

        if gs_start and gs_start > 0:
            current_report = gs_start
            print(f"📋 Starting from Google Sheet 'Start Number': {current_report}")
        else:
            # Priority 2: Local progress file
            current_report = load_progress()
            print(f"📂 Starting from local progress file: {current_report}")

    found_total = 0

    print(f"\n🎯 Target: Find {TARGET_FOUND} valid reports")
    print(f"🚀 Starting from report number: {current_report}\n")

    while found_total < TARGET_FOUND:
        BATCH_SIZE = 10
        batch = list(range(current_report, current_report + BATCH_SIZE))

        print(f"\n📦 Processing batch: {batch[0]} → {batch[-1]}")

        try:
            found_in_batch = run_search_session(
                report_numbers    = batch,
                found_callback    = on_found,
                not_found_callback= on_not_found,
                found_so_far      = found_total,
                target            = TARGET_FOUND,
            )
            found_total += found_in_batch

        except Exception as e:
            print(f"\n❌ Session error: {e}")
            print("   Saving progress and retrying next batch...")

        # Advance and save local progress
        current_report += BATCH_SIZE
        save_progress(current_report)

        print(f"\n📊 Progress: {found_total}/{TARGET_FOUND} valid reports found")

        if found_total >= TARGET_FOUND:
            break

        print("⏳ Waiting 5 seconds before next batch...")
        time.sleep(5)

    # Final summary
    print("\n" + "=" * 60)
    print(f"✅ DONE! Found {found_total} valid reports.")
    get_summary()
    print(f"\n📁 Local results saved to : crash_reports.xlsx")
    print(f"📊 Cloud results saved to : Google Sheets")
    print("=" * 60)


if __name__ == "__main__":
    main()