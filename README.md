# BuyCrash Report Automation

Automates crash report lookup on BuyCrash (LexisNexis) for Detroit Police Department.

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Install SeleniumBase browsers
```bash
seleniumbase install uc_driver
```

### 3. Create your .env file
```bash
cp .env.example .env
```
Then edit `.env` and fill in:
- `USERNAME` — your account username
- `PASSWORD_B64` — your base64-encoded password (as provided)
- `START_REPORT` — first report number to check
- `TARGET_FOUND` — how many valid reports to find (default: 3)

### 4. Run
```bash
# Normal run (resumes from last progress)
python main.py

# Start fresh
python main.py --reset

# Start from specific report number
python main.py --start 283746
```

## Output

Results are saved to `crash_reports.xlsx` with:
- **Green rows** = FOUND reports (with full details)
- **Red rows** = NOT FOUND report numbers

Columns saved:
| Column | Description |
|--------|-------------|
| Report Number | The report number checked |
| Report Type | e.g. Accident Report, Fatal Accident Report |
| Date of Incident | Date of the accident |
| Accident Location | Street / Cross Street |
| Last Names Involved | People listed in the report |
| Jurisdiction | Detroit Police Department |
| Status | FOUND or NOT FOUND |
| Checked At | Timestamp |

## How it works

1. Logs in via the `/login` API (no browser needed for login)
2. Opens Chrome in UC/CDP stealth mode
3. Injects session cookies into the browser
4. For each report number:
   - Fills the Report Number field (Option 1)
   - Solves the reCAPTCHA v2 automatically
   - Submits the search
   - Calls the search API with the CAPTCHA token
   - Saves result (found/not found) to Excel
5. Stops after finding TARGET_FOUND valid reports

## Report Number Logic

- Starts from `START_REPORT`
- Checks sequentially: 283746 → 283747 → 283748 ...
- Saves ALL checked numbers (found and not found)
- Progress is saved after each batch so you can resume after interruption

## Troubleshooting

**CAPTCHA not solving:** SeleniumBase's `solve_captcha()` works best with a visible
browser window (headless=False). Make sure you're not running in a restricted environment.

**Login fails:** Double-check your base64 password. Test decoding it:
```python
import base64
print(base64.b64decode("your_b64_string").decode())
```

**Session expires mid-run:** The script will catch the error and retry the batch.
If it keeps failing, restart with `python main.py` (it will resume from progress file).