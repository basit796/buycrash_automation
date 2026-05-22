"""
progress.py
-----------
Tracks the last checked report number so the script
can resume from where it left off after a crash or restart.
"""
import os
from config import PROGRESS_FILE

DEFAULT_START = 1000000   # fallback if no progress file and no sheet number


def load_progress() -> int:
    """Return the last saved report number, or DEFAULT_START if no file."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            content = f.read().strip()
            if content.isdigit():
                num = int(content)
                print(f"Resuming from progress file: report #{num}")
                return num
    print(f"No progress file found — defaulting to {DEFAULT_START}")
    return DEFAULT_START


def save_progress(report_number: int):
    """Save current report number to progress file."""
    with open(PROGRESS_FILE, "w") as f:
        f.write(str(report_number))


def reset_progress():
    """Delete progress file to start from scratch."""
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        print("Progress reset.")