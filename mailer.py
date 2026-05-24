"""
mailer.py
---------
Sends alert and summary emails via Gmail SMTP.
Credentials come from the Config sheet (loaded at runtime).

Gmail setup required:
  1. Enable 2-Step Verification on the Gmail account
  2. Go to: Google Account -> Security -> App Passwords
  3. Generate a 16-char app password (e.g. "dxfy esji ylly xbdo")
  4. Put that in Config sheet B21 (Alert Email Password)
  5. Put the Gmail address in Config sheet B20 (Alert Email)
"""
import smtplib
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


def _send(to_email: str, app_password: str, subject: str, body: str):
    """Core send function using Gmail SMTP."""
    if not to_email or not app_password:
        print("   [MAIL] No email configured — skipping alert")
        return

    try:
        msg                    = MIMEMultipart("alternative")
        msg["Subject"]         = subject
        msg["From"]            = to_email
        msg["To"]              = to_email
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(to_email, app_password)
            server.sendmail(to_email, to_email, msg.as_string())

        print(f"   [MAIL] Sent: {subject}")
    except Exception as e:
        print(f"   [MAIL] Failed to send email: {e}")


# -------------------------------------------------------------------
# PUBLIC ALERT FUNCTIONS
# -------------------------------------------------------------------

def send_otp_required(cfg: dict, slot_idx: int, account_label: str,
                      username: str = "", password: str = ""):
    """Alert: OTP screen appeared for an account — includes credentials."""
    subject = f"[BuyCrash] OTP Required — {account_label}"
    body = (
        f"OTP Required\n"
        f"{'='*40}\n"
        f"Time           : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Slot           : {slot_idx}\n"
        f"Account        : {account_label}\n"
        f"Username       : {username}\n"
        f"Password       : {password}\n\n"
        f"Action needed:\n"
        f"  1. Log into the account above\n"
        f"  2. Check inbox for the OTP code\n"
        f"  3. Paste it into Google Sheet → 'Start Number' tab → cell B2\n\n"
        f"The script will wait {cfg.get('otp_timeout_min', 60)} minutes "
        f"before skipping this account.\n"
    )
    _send(cfg.get("alert_email", ""), cfg.get("alert_password", ""), subject, body)


def send_consecutive_errors(cfg: dict, report_number: str, error_msg: str,
                             found_total: int, searches_done: int, elapsed_sec: float):
    """Alert: 20 consecutive errors — script is stopping."""
    subject = "[BuyCrash] STOPPED — 20 Consecutive Errors"
    body = (
        f"Script stopped due to consecutive errors\n"
        f"{'='*40}\n"
        f"Time           : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Last report    : {report_number}\n"
        f"Last error     : {error_msg[:200]}\n\n"
        f"Run summary\n"
        f"{'='*40}\n"
        f"Reports found  : {found_total}\n"
        f"Total searches : {searches_done}\n"
        f"Time elapsed   : {_fmt_elapsed(elapsed_sec)}\n"
    )
    _send(cfg.get("alert_email", ""), cfg.get("alert_password", ""), subject, body)


def send_user_stop(cfg: dict, found_total: int, searches_done: int, elapsed_sec: float):
    """Alert: user typed 'stop' in the Control cell."""
    subject = "[BuyCrash] Stopped by User Command"
    body = (
        f"Script stopped by user (Control cell = 'stop')\n"
        f"{'='*40}\n"
        f"Time           : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"Run summary\n"
        f"{'='*40}\n"
        f"Reports found  : {found_total}\n"
        f"Total searches : {searches_done}\n"
        f"Time elapsed   : {_fmt_elapsed(elapsed_sec)}\n"
    )
    _send(cfg.get("alert_email", ""), cfg.get("alert_password", ""), subject, body)


def send_crash(cfg: dict, exc: Exception, found_total: int,
               searches_done: int, elapsed_sec: float):
    """Alert: unhandled exception crashed the script."""
    subject = "[BuyCrash] CRASHED — Unhandled Exception"
    body = (
        f"Script crashed with an unhandled exception\n"
        f"{'='*40}\n"
        f"Time           : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Exception      : {type(exc).__name__}: {str(exc)[:300]}\n\n"
        f"Traceback\n"
        f"{'='*40}\n"
        f"{traceback.format_exc()[:1000]}\n\n"
        f"Run summary\n"
        f"{'='*40}\n"
        f"Reports found  : {found_total}\n"
        f"Total searches : {searches_done}\n"
        f"Time elapsed   : {_fmt_elapsed(elapsed_sec)}\n"
    )
    _send(cfg.get("alert_email", ""), cfg.get("alert_password", ""), subject, body)


def send_success(cfg: dict, found_total: int, target: int,
                 searches_done: int, elapsed_sec: float,
                 not_found_count: int, error_count: int):
    """Alert: target reached — run completed successfully."""
    subject = f"[BuyCrash] SUCCESS — Found {found_total}/{target} Reports"
    body = (
        f"Target reached! Script completed successfully.\n"
        f"{'='*40}\n"
        f"Time completed : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"Run Summary\n"
        f"{'='*40}\n"
        f"Reports found  : {found_total} / {target}\n"
        f"Not found      : {not_found_count}\n"
        f"Errors         : {error_count}\n"
        f"Total searches : {searches_done}\n"
        f"Time elapsed   : {_fmt_elapsed(elapsed_sec)}\n"
        f"Success rate   : {(found_total / searches_done * 100):.1f}% of all searches\n\n"
        f"Results saved to:\n"
        f"  - Google Sheets (Found / Not Found / Errors tabs)\n"
        f"  - Local file: crash_reports.xlsx\n"
    )
    _send(cfg.get("alert_email", ""), cfg.get("alert_password", ""), subject, body)


def send_ip_rotated(cfg: dict, old_proxy_idx: int, new_proxy_idx: int,
                    new_proxy: str, rotation_num: int, max_rotations: int,
                    report_num: int):
    """Alert: IP rotated after all slots hit search limit."""
    display_proxy = new_proxy
    try:
        if "@" in new_proxy:
            scheme_creds, rest = new_proxy.split("@", 1)
            scheme, creds      = scheme_creds.split("//", 1)
            user               = creds.split(":")[0]
            display_proxy      = f"{scheme}//{user}:****@{rest}"
    except Exception:
        display_proxy = "****"

    subject = f"[BuyCrash] IP Rotated ({rotation_num}/{max_rotations})"
    body = (
        f"IP rotated — all 4 slots hit search limit\n"
        f"{'='*40}\n"
        f"Time           : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Rotation       : {rotation_num} of {max_rotations}\n"
        f"New proxy      : {display_proxy}\n"
        f"Resume from    : report #{report_num}\n"
    )
    _send(cfg.get("alert_email", ""), cfg.get("alert_password", ""), subject, body)


def send_proxies_exhausted(cfg: dict, found_total: int, searches_done: int,
                           elapsed_sec: float, report_num: int,
                           fallback_wait_min: int):
    """Alert: all proxies exhausted, falling back to timed pause."""
    subject = "[BuyCrash] All Proxies Exhausted — Waiting"
    body = (
        f"All proxy IPs used and all hit search limits.\n"
        f"Falling back to {fallback_wait_min}-min wait before retrying.\n"
        f"{'='*40}\n"
        f"Time           : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Resume from    : report #{report_num}\n\n"
        f"Progress\n"
        f"{'='*40}\n"
        f"Reports found  : {found_total}\n"
        f"Total searches : {searches_done}\n"
        f"Time elapsed   : {_fmt_elapsed(elapsed_sec)}\n"
    )
    _send(cfg.get("alert_email", ""), cfg.get("alert_password", ""), subject, body)


def send_restart(cfg: dict, found_total: int, searches_done: int,
                 elapsed_sec: float, new_start: int):
    """Alert: user triggered restart."""
    subject = "[BuyCrash] Restarting — User Command"
    body = (
        f"Script restarting (Control cell = 'restart')\n"
        f"{'='*40}\n"
        f"Time           : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Resuming from  : report #{new_start}\n\n"
        f"Progress so far\n"
        f"{'='*40}\n"
        f"Reports found  : {found_total}\n"
        f"Total searches : {searches_done}\n"
        f"Time elapsed   : {_fmt_elapsed(elapsed_sec)}\n"
    )
    _send(cfg.get("alert_email", ""), cfg.get("alert_password", ""), subject, body)


# -------------------------------------------------------------------
# HELPER
# -------------------------------------------------------------------

def _fmt_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    h, rem  = divmod(seconds, 3600)
    m, s    = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"