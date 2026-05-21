"""
main.py
-------
Orchestrator for BuyCrash report automation.

Usage:
    python main.py                  # Run using start number from Google Sheet
    python main.py --reset          # Reset local progress
    python main.py --start 1525123  # Override start number

Slot rotation (all values in config.py):
  Slot 0  — Account 1  (reports 1-15)
  Slot 1  — Account 2  (reports 16-30)
  Slot 2  — Account 3  (reports 31-45)
  Slot 3  — No-login   (reports 46-60)
  3-min pause between slots, then repeat cycle.

Rate-limit handling:
  SEARCH_LIMIT_REACHED → 5-min pause → skip to next slot.

OTP handling:
  OTP screen → wait 30 min for code in Sheet B2 → if none, skip to next slot.

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
)
from progress import load_progress, save_progress, reset_progress
from excel_handler import save_found_report, save_not_found_report, get_summary
from searcher import get_session_for_slot, run_slot_batch
import sheets_handler


# -------------------------------------------------------------------
# Helpers — slot labels
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
    """Print a live countdown, ticking every `interval` seconds."""
    for remaining in range(seconds, 0, -interval):
        mins, secs = divmod(remaining, 60)
        print(f"   [{label}] Resuming in {mins}m {secs:02d}s...  ", end="\r")
        time.sleep(min(interval, remaining))
    print()


def _inter_slot_pause(from_slot: int, to_slot: int):
    print(f"\n   [PAUSE] {INTER_BATCH_PAUSE_SEC // 60} min between "
          f"{_slot_label(from_slot)} → {_slot_label(to_slot)}")
    _countdown("INTER-SLOT PAUSE", INTER_BATCH_PAUSE_SEC)


def _limit_pause(slot_idx: int):
    print(f"\n   [LIMIT PAUSE] {LIMIT_PAUSE_SEC // 60} min after limit on "
          f"{_slot_label(slot_idx)}, then moving to next slot")
    _countdown("LIMIT PAUSE", LIMIT_PAUSE_SEC)


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
    print(f"\n  Batch size        : {BATCH_SIZE} reports / slot")
    print(f"  Inter-slot pause  : {INTER_BATCH_PAUSE_SEC // 60} min")
    print(f"  Limit pause       : {LIMIT_PAUSE_SEC // 60} min then next slot")
    print("=" * 60)

    print("\nChecking Google Sheets connection...")
    sheets_handler.test_connection()
    print()

    if args.reset:
        reset_progress()

    # Starting report number
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
    # MAIN LOOP — cycles through slots until target is reached
    # ================================================================
    while found_total < TARGET_FOUND:
        cycle_num   += 1
        cycle_start  = current_report

        print(f"\n{'#'*60}")
        print(f"  CYCLE #{cycle_num:03d}  —  starting at report {cycle_start}")
        print(f"  Found so far: {found_total}/{TARGET_FOUND}")
        print(f"{'#'*60}")

        # Track which slots we actually ran this cycle (for pause logic)
        last_active_slot = None

        for slot_idx in range(TOTAL_SLOTS):

            if found_total >= TARGET_FOUND:
                break

            slot_start = current_report + slot_idx * BATCH_SIZE
            batch      = list(range(slot_start, slot_start + BATCH_SIZE))

            print(f"\n{'='*60}")
            print(f"  {_slot_label(slot_idx)}")
            print(f"  Reports : {batch[0]} → {batch[-1]}")
            print(f"  Found   : {found_total}/{TARGET_FOUND}")
            print(f"{'='*60}")

            # -- 3-min inter-slot pause (not before the very first slot) --
            if last_active_slot is not None:
                _inter_slot_pause(last_active_slot, slot_idx)

            # -- Acquire session --
            try:
                api_session = get_session_for_slot(slot_idx)
            except Exception as e:
                err = str(e)
                if "OTP_TIMEOUT" in err:
                    acc_label = _slot_label(slot_idx)
                    print(f"\n   [OTP TIMEOUT] No OTP received for {acc_label}")
                    print(f"   Skipping to next slot.")
                    sheets_handler.save_error(
                        f"OTP_TIMEOUT_SLOT{slot_idx}",
                        f"OTP not provided for {acc_label} within timeout"
                    )
                    last_active_slot = slot_idx
                    continue
                elif "LOGIN_FAILED" in err:
                    print(f"\n   [LOGIN FAILED] {_slot_label(slot_idx)} — skipping")
                    last_active_slot = slot_idx
                    continue
                else:
                    print(f"\n   [SESSION ERROR] {_slot_label(slot_idx)}: {e}")
                    last_active_slot = slot_idx
                    continue

            # -- Run batch --
            found_in_slot, status = run_slot_batch(
                slot_idx        = slot_idx,
                api_session     = api_session,
                report_numbers  = batch,
                found_callback     = on_found,
                not_found_callback = on_not_found,
                error_callback     = on_error,
                found_so_far    = found_total,
                target          = TARGET_FOUND,
            )

            found_total   += found_in_slot
            last_active_slot = slot_idx

            print(f"\n   [{_slot_label(slot_idx)}] Done. "
                  f"Found this slot: {found_in_slot} | Total: {found_total}/{TARGET_FOUND}")

            if status == "limit":
                _limit_pause(slot_idx)
                # Move to next slot (loop continues naturally)

            elif status == "session":
                print(f"   [SESSION] Slot {slot_idx} session lost — moving to next slot")

            if found_total >= TARGET_FOUND:
                break

        # Advance current_report by one full cycle (4 slots × BATCH_SIZE)
        current_report += TOTAL_SLOTS * BATCH_SIZE
        save_progress(current_report)
        print(f"\nProgress saved — next cycle starts at {current_report}")

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