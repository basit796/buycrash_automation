"""
main.py
-------
Orchestrator for BuyCrash report automation.

Usage:
    python main.py                  # Run from last saved progress
    python main.py --reset          # Start fresh from START_REPORT in .env
    python main.py --start 283746   # Start from a specific report number
"""
import sys
import argparse
import time
from config import TARGET_FOUND, START_REPORT
from progress import load_progress, save_progress, reset_progress
from excel_handler import save_found_report, save_not_found_report, get_summary
from searcher import run_search_session


# -------------------------------------------------------------------
# Callbacks
# -------------------------------------------------------------------

def on_found(record: dict):
    save_found_report(record)

def on_not_found(report_number: str):
    save_not_found_report(report_number)


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="BuyCrash Report Automation")
    parser.add_argument("--reset", action="store_true", help="Reset progress and start fresh")
    parser.add_argument("--start", type=int, help="Start from a specific report number")
    args = parser.parse_args()

    print("=" * 60)
    print("  BuyCrash Report Automation")
    print("=" * 60)

    # Handle reset
    if args.reset:
        reset_progress()

    # Determine starting report number
    if args.start:
        current_report = args.start
        print(f"📌 Starting from specified report number: {current_report}")
    else:
        current_report = load_progress()

    found_total = 0

    print(f"\n🎯 Target: Find {TARGET_FOUND} valid reports")
    print(f"🚀 Starting from report number: {current_report}\n")

    while found_total < TARGET_FOUND:
        # Build a small batch of report numbers to check
        # We process in batches of 10 to avoid very long browser sessions
        BATCH_SIZE = 10
        batch = list(range(current_report, current_report + BATCH_SIZE))

        print(f"\n📦 Processing batch: {batch[0]} → {batch[-1]}")

        try:
            found_in_batch = run_search_session(
                report_numbers=batch,
                found_callback=on_found,
                not_found_callback=on_not_found,
            )
            found_total += found_in_batch

        except Exception as e:
            print(f"\n❌ Session error: {e}")
            print("   Saving progress and will retry next batch...")

        # Update progress to next batch
        current_report += BATCH_SIZE
        save_progress(current_report)

        print(f"\n📊 Progress: {found_total}/{TARGET_FOUND} valid reports found")

        if found_total >= TARGET_FOUND:
            break

        # Short pause between batches
        import time
        print("⏳ Waiting 5 seconds before next batch...")
        time.sleep(5)

    # Final summary
    print("\n" + "=" * 60)
    print(f"✅ DONE! Found {found_total} valid reports.")
    get_summary()
    print(f"\n📁 Results saved to: crash_reports.xlsx")
    print("=" * 60)


if __name__ == "__main__":
    main()