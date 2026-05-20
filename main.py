"""
main.py
-------
Orchestrator for BuyCrash report automation.

Usage:
    python main.py                  # Run using start number from Google Sheet
    python main.py --reset          # Reset local progress
    python main.py --start 283746   # Override start number

Account rotation rules:
    - Rotates to the next account on every batch boundary
    - Rotates immediately when SEARCH_LIMIT_REACHED is hit
    - If ALL accounts hit the limit: dynamic pause schedule (no re-login forced)
      Pause schedule (minutes): 3 → 6 → 15 → 30 → 60, repeats once, then terminates

Data is saved to:
  - Local Excel  (crash_reports.xlsx)
  - Google Sheets (Found / Not Found / Errors tabs)
"""
import argparse
import sys
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

# Pause schedule (minutes) when ALL accounts hit rate limit simultaneously.
# Goes through this list twice; on the third cycle → terminates execution.
_ALL_LIMIT_PAUSE_SCHEDULE = [3, 6, 15, 30, 60]
_MAX_ALL_LIMIT_CYCLES     = 2   # after 2 full cycles → give up


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

    found_total      = 0
    account_idx      = 0          # ever-incrementing; mod len gives real slot
    limited_accs     = set()      # which account indices hit the limit this round

    # All-limit pause tracking
    all_limit_step   = 0          # position in _ALL_LIMIT_PAUSE_SCHEDULE
    all_limit_cycle  = 0          # how many full cycles completed

    print(f"\nTarget  : Find {TARGET_FOUND} valid reports")
    print(f"Starting: report number {current_report}")
    print(f"Accounts: {len(ACCOUNTS)} available")
    print(f"Pause schedule (all-limit): {_ALL_LIMIT_PAUSE_SCHEDULE} min × {_MAX_ALL_LIMIT_CYCLES} cycles\n")

    while found_total < TARGET_FOUND:
        BATCH_SIZE = 10
        real_idx   = account_idx % len(ACCOUNTS)
        account    = ACCOUNTS[real_idx]

        # ── All accounts rate-limited → dynamic pause ──────────────────────
        if len(limited_accs) >= len(ACCOUNTS):

            # Check if we've exhausted all cycles → terminate
            if all_limit_cycle >= _MAX_ALL_LIMIT_CYCLES:
                print(f"\n[LIMIT-ALL] All {len(ACCOUNTS)} accounts hit the limit "
                      f"{_MAX_ALL_LIMIT_CYCLES} full pause cycles in a row.")
                print("[LIMIT-ALL] Giving up — the site's rate cap appears permanent for today.")
                print(f"[LIMIT-ALL] Progress saved at report {current_report}.")
                print("[LIMIT-ALL] Re-run tomorrow or add more accounts.")
                break

            wait_min = _ALL_LIMIT_PAUSE_SCHEDULE[all_limit_step]
            wait_sec = wait_min * 60

            print(f"\n[LIMIT-ALL] All {len(ACCOUNTS)} accounts have hit the rate limit.")
            print(f"[LIMIT-ALL] Pause #{all_limit_step + 1} of cycle {all_limit_cycle + 1}"
                  f"/{_MAX_ALL_LIMIT_CYCLES} — waiting {wait_min} min...")

            for remaining in range(wait_sec, 0, -15):
                print(f"[LIMIT-ALL] Resuming in {remaining}s...  ", end="\r")
                time.sleep(15)
            print()

            # Advance through the schedule
            all_limit_step += 1
            if all_limit_step >= len(_ALL_LIMIT_PAUSE_SCHEDULE):
                all_limit_step  = 0
                all_limit_cycle += 1
                if all_limit_cycle < _MAX_ALL_LIMIT_CYCLES:
                    print(f"[LIMIT-ALL] Completed cycle {all_limit_cycle}/{_MAX_ALL_LIMIT_CYCLES}"
                          f" — restarting pause schedule at 3 min")

            # Clear limit flags and restart from account 1
            limited_accs.clear()
            account_idx = 0
            real_idx    = 0
            account     = ACCOUNTS[0]
            print(f"[LIMIT-ALL] Retrying with account 1: {account['username']}\n")

        batch = list(range(current_report, current_report + BATCH_SIZE))

        print(f"\n{'='*60}")
        print(f"  Batch  : {batch[0]} -> {batch[-1]}")
        print(f"  Account: {real_idx + 1} / {len(ACCOUNTS)}  ({account['username']})")
        print(f"  Found  : {found_total}/{TARGET_FOUND}")
        if limited_accs:
            print(f"  Limited: accounts {[i+1 for i in sorted(limited_accs)]}")
        if all_limit_cycle > 0 or all_limit_step > 0:
            print(f"  Pauses : cycle {all_limit_cycle+1}/{_MAX_ALL_LIMIT_CYCLES}, "
                  f"step {all_limit_step}/{len(_ALL_LIMIT_PAUSE_SCHEDULE)}")
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
                error_callback     = on_error,
            )
            found_total += found_in_batch

            # Successful batch — clear this account from limited set
            if real_idx in limited_accs:
                limited_accs.discard(real_idx)
                print(f"[ROTATE] Account {real_idx+1} worked — removed from limited set")

            # If a full batch succeeded without any limit, reset the pause schedule
            if not limit_hit and all_limit_step > 0:
                print(f"[LIMIT-ALL] Successful batch — resetting pause schedule")
                all_limit_step  = 0
                all_limit_cycle = 0

        except Exception as e:
            print(f"\nSession error: {e}")
            print("Saving progress and continuing with next account...")

        # Mark this account as limited (NO cookie deletion — re-login doesn't help)
        if limit_hit:
            limited_accs.add(real_idx)

        # Advance report number only if limit was NOT hit mid-batch
        if not limit_hit:
            current_report += BATCH_SIZE

        save_progress(current_report)
        print(f"\nProgress: {found_total}/{TARGET_FOUND} valid reports found")

        if found_total >= TARGET_FOUND:
            break

        # Rotate to next account
        next_real = (account_idx + 1) % len(ACCOUNTS)
        if limit_hit:
            print(f"[ROTATE] Rate limit — switching "
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