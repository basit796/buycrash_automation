"""
Tracks the last checked report number so the script
can resume from where it left off after a crash or restart.
"""
import os
from config import PROGRESS_FILE, START_REPORT


def load_progress() -> int:
    """Return the last checked report number, or START_REPORT if fresh start."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            content = f.read().strip()
            if content.isdigit():
                num = int(content)
                print(f"📌 Resuming from report number: {num}")
                return num
    print(f"📌 Starting fresh from report number: {START_REPORT}")
    return START_REPORT


def save_progress(report_number: int):
    """Save current report number to progress file."""
    with open(PROGRESS_FILE, "w") as f:
        f.write(str(report_number))


def reset_progress():
    """Delete progress file to start from scratch."""
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        print("🔄 Progress reset.")