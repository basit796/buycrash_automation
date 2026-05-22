"""
main.py
-------
Orchestrator for BuyCrash report automation.

Usage:
    python main.py                  # Run using start number from Google Sheet
    python main.py --reset          # Reset local progress
    python main.py --start 1525123  # Override start number

Slot rotation (all values in config.py):
  Slot 0  — Account 1
  Slot 1  — Account 2
  Slot 2  — Account 3
  Slot 3  — No-login (direct URL)
  3-min pause between slots.

Mid-batch continuity:
  If a slot hits a limit/session error on report N out of 15,
  the NEXT slot resumes from report N (not from N+remaining).
  No reports are ever skipped due to an early slot exit.

Rate-limit handling:
  SEARCH_LIMIT_REACHED → 5-min pause → next slot resumes from exact report.
  ALL 4 slots limit in same cycle → 15-min pause → restart cycle from same report.

OTP handling:
  OTP screen → wait 30 min → if no code, skip slot, next slot resumes same report.

Data saved to:
  - Local Excel  (crash_reports.xlsx)
  - Google Sheets (Found / Not Found / Errors tabs)
"""
import argparse
import time

from config import (
    TARGET_FOUND, START_REPORT,
    ACCOUNTS, NO_LOGIN_SLOT, TOTAL_SLOTS, BATCH_SIZE,
    INTER_BATCH_PAUSE_SEC, LIMIT_PAUSE_SEC,
    ALL_SLOTS_LIMIT_PAUSE_SEC,
)
from progress import load_progress, save_progress, reset_progress
from excel_handler import save_found_report, save_not_found_report, get_summary
from searcher import get_session_for_slot, run_slot_batch
import sheets_handler


# -------------------------------------------------------------------
# Slot label helper
# -------------------------------------------------------------------

def _slot_label(slot_idx: int) -> str:
    if slot_idx == NO_LOGIN_SLOT:
        return "Slot 3 / NO-LOGIN"
    acc = ACCOUNTS[slot_idx] if slot_idx < len(ACCOUNTS) else None
    if acc:
        return f"Slot {slot_idx} / Account {slot_idx + 1}: {acc['username']}"
    return f"Slot {slot_idx} (no account configured)"


# -------------------------------------------------------------------
# Callbacks
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


def on_error(report_number: str, error_msg: str):
    print(f"   [ERROR FINAL] {report_number}: {error_msg[:80]}")
    sheets_handler.save_error(report_number, error_msg)
    save_not_found_report(f"ERROR:{report_number}")


# -------------------------------------------------------------------
# Pause helpers
# -------------------------------------------------------------------

def _countdown(label: str, seconds: int, interval: int = 30):
    for remaining in range(seconds, 0, -interval):
        mins, secs = divmod(remaining, 60)
        print(f"   [{label}] Resuming in {mins}m {secs:02d}s...  ", end="\r")
        time.sleep(min(interval, remaining))
    print()


def _inter_slot_pause(from_slot: int, to_slot: int):
    print(f"\n   [INTER-SLOT PAUSE] {INTER_BATCH_PAUSE_SEC // 60} min  "
          f"({_slot_label(from_slot)} → {_slot_label(to_slot)})")
    _countdown("INTER-SLOT", INTER_BATCH_PAUSE_SEC)


def _limit_pause(slot_idx: int, report_num: int):
    print(f"\n   [LIMIT PAUSE] {LIMIT_PAUSE_SEC // 60} min after limit on "
          f"{_slot_label(slot_idx)} — next slot resumes from report {report_num}")
    _countdown("LIMIT PAUSE", LIMIT_PAUSE_SEC)


def _all_slots_limit_pause(report_num: int):
    mins = ALL_SLOTS_LIMIT_PAUSE_SEC // 60
    print(f"\n{'!'*60}")
    print(f"  ALL 4 SLOTS HIT SEARCH LIMIT")
    print(f"  Pausing {mins} min then retrying from report {report_num}")
    print(f"{'!'*60}")
    _countdown("ALL-SLOTS LIMIT PAUSE", ALL_SLOTS_LIMIT_PAUSE_SEC)


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="BuyCrash Report Automation")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--start", type=int)
    args = parser.parse_args()

    print("=" * 60)
    print("  BuyCrash Report Automation — 4-Slot Rotation")
    print("=" * 60)
    for i in range(TOTAL_SLOTS):
        print(f"  {_slot_label(i)}")
    print(f"\n  Batch size          : {BATCH_SIZE} reports / slot")
    print(f"  Inter-slot pause    : {INTER_BATCH_PAUSE_SEC // 60} min")
    print(f"  Per-limit pause     : {LIMIT_PAUSE_SEC // 60} min then next slot")
    print(f"  All-slots-limit     : {ALL_SLOTS_LIMIT_PAUSE_SEC // 60} min then retry cycle")
    print(f"  Mid-batch stop      : resumes from exact report, nothing skipped")
    print("=" * 60)

    print("\nChecking Google Sheets connection...")
    sheets_handler.test_connection()
    print()

    if args.reset:
        reset_progress()

    if args.start:
        current_report = args.start
        print(f"Starting from CLI: {current_report}")
    else:
        gs_start = sheets_handler.get_start_number()
        if gs_start and gs_start > 0:
            current_report = gs_start
            print(f"Starting from Google Sheet: {current_report}")
        else:
            current_report = load_progress()
            print(f"Starting from progress file: {current_report}")

    found_total = 0
    cycle_num   = 0

    print(f"\nTarget  : {TARGET_FOUND} valid reports")
    print(f"Starting: report #{current_report}\n")

    # ================================================================
    # MAIN LOOP
    # ================================================================
    while found_total < TARGET_FOUND:
        cycle_num  += 1
        # cursor tracks exactly which report number the next slot should start at
        cursor      = current_report
        limit_count = 0   # how many slots hit SEARCH_LIMIT_REACHED this cycle

        print(f"\n{'#'*60}")
        print(f"  CYCLE #{cycle_num:03d}  —  cursor at report {cursor}")
        print(f"  Found so far: {found_total}/{TARGET_FOUND}")
        print(f"{'#'*60}")

        last_active_slot    = None
        cycle_end_cursor    = cursor   # will advance as slots complete cleanly

        for slot_idx in range(TOTAL_SLOTS):

            if found_total >= TARGET_FOUND:
                break

            # Build this slot's batch starting from the current cursor
            batch = list(range(cursor, cursor + BATCH_SIZE))

            print(f"\n{'='*60}")
            print(f"  {_slot_label(slot_idx)}")
            print(f"  Reports : {batch[0]} → {batch[-1]}")
            print(f"  Found   : {found_total}/{TARGET_FOUND}")
            print(f"{'='*60}")

            # Inter-slot pause (not before the first slot of the cycle)
            if last_active_slot is not None:
                _inter_slot_pause(last_active_slot, slot_idx)

            # Acquire session
            try:
                api_session = get_session_for_slot(slot_idx)
            except Exception as e:
                err = str(e)
                if "OTP_TIMEOUT" in err:
                    acc_label = _slot_label(slot_idx)
                    print(f"\n   [OTP TIMEOUT] No OTP for {acc_label}")
                    print(f"   Skipping slot — next slot resumes from report {cursor}")
                    sheets_handler.save_error(
                        f"OTP_TIMEOUT_SLOT{slot_idx}",
                        f"OTP not provided for {acc_label} within timeout"
                    )
                    # cursor stays the same — next slot picks up here
                elif "LOGIN_FAILED" in err:
                    print(f"\n   [LOGIN FAILED] {_slot_label(slot_idx)} — skipping")
                    # cursor stays the same
                else:
                    print(f"\n   [SESSION ERROR] {_slot_label(slot_idx)}: {e}")
                    # cursor stays the same
                last_active_slot = slot_idx
                continue

            # Run the batch
            found_in_slot, next_report, status = run_slot_batch(
                slot_idx           = slot_idx,
                api_session        = api_session,
                report_numbers     = batch,
                found_callback     = on_found,
                not_found_callback = on_not_found,
                error_callback     = on_error,
                found_so_far       = found_total,
                target             = TARGET_FOUND,
            )

            found_total      += found_in_slot
            last_active_slot  = slot_idx

            print(f"\n   [{_slot_label(slot_idx)}] Done. "
                  f"Found this slot: {found_in_slot} | "
                  f"Total: {found_total}/{TARGET_FOUND} | "
                  f"Next report: {next_report}")

            if status == "ok":
                # Slot completed its full batch — advance cursor past this batch
                cursor           = next_report
                cycle_end_cursor = cursor

            elif status == "limit":
                # Slot hit rate limit on report `next_report`
                # next slot resumes from that exact report
                limit_count += 1
                cursor       = next_report   # resume HERE, not after the batch
                _limit_pause(slot_idx, cursor)

            elif status == "session":
                # Session died mid-batch — next slot resumes from same report
                cursor = next_report
                print(f"   [SESSION] Slot {slot_idx} session lost — "
                      f"next slot resumes from {cursor}")

            save_progress(cursor)

            if found_total >= TARGET_FOUND:
                break

        # ── All 4 slots done for this cycle ──────────────────────────
        if found_total >= TARGET_FOUND:
            break

        if limit_count == TOTAL_SLOTS:
            # Every single slot was rate-limited this cycle
            _all_slots_limit_pause(cursor)
            # Don't advance cursor — retry entire cycle from same position
        else:
            # Normal end of cycle — cursor already advanced by completed slots
            current_report = cursor

        save_progress(current_report)
        print(f"\nCycle #{cycle_num:03d} complete. "
              f"Next cycle from report #{current_report}. "
              f"Found: {found_total}/{TARGET_FOUND}")

    # ================================================================
    # DONE
    # ================================================================
    print("\n" + "=" * 60)
    print(f"DONE! Found {found_total}/{TARGET_FOUND} valid reports.")
    get_summary()
    print(f"\nLocal  : crash_reports.xlsx")
    print(f"Cloud  : Google Sheets")
    print("=" * 60)


if __name__ == "__main__":
    main()