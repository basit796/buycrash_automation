"""
api.py — FastAPI with built-in Swagger UI at /docs
"""
import os, subprocess, sys, threading
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import sheets_handler

load_dotenv()

API_KEY     = os.getenv("API_KEY", "")
SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "main.py")
PYTHON_BIN  = sys.executable

app = FastAPI(
    title="BuyCrash Automation API",
    description="Control and monitor the BuyCrash report scraper. Use /docs for Swagger UI.",
    version="1.0.0",
)

_state = {
    "status": "idle", "pid": None, "started_at": None,
    "stopped_at": None, "start_report": None,
    "exit_code": None, "log_tail": [],
}
_process = None
_lock = threading.Lock()


# --- Auth ---

def _auth(x_api_key: str = Header(default="")):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")


# --- Process management ---

def _watch(proc):
    lines = []
    for line in iter(proc.stdout.readline, b""):
        decoded = line.decode("utf-8", errors="replace").rstrip()
        print(decoded)
        lines.append(decoded)
        if len(lines) > 50:
            lines.pop(0)
        with _lock:
            _state["log_tail"] = list(lines)
    proc.wait()
    with _lock:
        _state["status"]     = "stopped" if proc.returncode == 0 else "error"
        _state["exit_code"]  = proc.returncode
        _state["stopped_at"] = datetime.now().isoformat()
        _state["pid"]        = None


def _start(start_report: int = None):
    global _process
    with _lock:
        if _state["status"] == "running":
            raise HTTPException(status_code=400, detail="Script is already running")
    cmd = [PYTHON_BIN, SCRIPT_PATH]
    if start_report:
        cmd += ["--start", str(start_report)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=1)
    _process = proc
    with _lock:
        _state.update(status="running", pid=proc.pid,
                      started_at=datetime.now().isoformat(),
                      stopped_at=None, exit_code=None,
                      start_report=start_report, log_tail=[])
    threading.Thread(target=_watch, args=(proc,), daemon=True).start()


def _write_control(cmd: str):
    try:
        import sheets_handler
        from config import SHEET_CONFIG, CFG_ROW
        def _do():
            sheets_handler._get_spreadsheet().worksheet(SHEET_CONFIG)\
                .update(CFG_ROW["control"], [[cmd]])
        sheets_handler._with_retry(_do)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sheet write failed: {e}")


def _require_running():
    if _state["status"] != "running":
        raise HTTPException(status_code=400, detail="Script is not running")


# --- Models ---

class StartBody(BaseModel):
    start_report: Optional[int] = None


# --- Endpoints ---

@app.get("/health", tags=["General"], summary="Health check")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


@app.get("/status", tags=["General"], summary="Current run status and last 50 log lines")
def status(x_api_key: str = Header(default="")):
    _auth(x_api_key)
    with _lock:
        s = dict(_state)
    if s["status"] == "running" and s["started_at"]:
        sec = (datetime.now() - datetime.fromisoformat(s["started_at"])).total_seconds()
        h, r = divmod(int(sec), 3600); m, sc = divmod(r, 60)
        s["uptime"] = f"{h}h {m}m {sc}s"
    return s


@app.get("/logs", tags=["General"], summary="Last 50 lines of script output")
def logs(x_api_key: str = Header(default="")):
    _auth(x_api_key)
    with _lock:
        lines = list(_state["log_tail"])
    return {"lines": lines, "count": len(lines)}


@app.post("/start", tags=["Control"], summary="Start the script")
def start(body: StartBody = StartBody(), x_api_key: str = Header(default="")):
    _auth(x_api_key)
    _start(body.start_report)
    return {"message": "Script started", "pid": _state["pid"], "started": _state["started_at"]}


@app.post("/stop", tags=["Control"], summary="Stop the script cleanly")
def stop(x_api_key: str = Header(default="")):
    _auth(x_api_key); _require_running()
    _write_control("stop")
    return {"message": "Stop command sent"}


@app.post("/pause", tags=["Control"], summary="Pause the script for 30 minutes")
def pause(x_api_key: str = Header(default="")):
    _auth(x_api_key); _require_running()
    _write_control("pause")
    return {"message": "Pause command sent (30 min)"}


@app.post("/restart", tags=["Control"], summary="Restart the script (reload config)")
def restart(x_api_key: str = Header(default="")):
    _auth(x_api_key)
    if _state["status"] == "running":
        _write_control("restart")
        return {"message": "Restart command sent"}
    _start()
    return {"message": "Was idle — started fresh", "pid": _state["pid"]}


# --- Account Creator Background Thread & State ---

_creator_state = {
    "status": "idle",
    "created_accounts": [],
    "logs": []
}
_creator_lock = threading.Lock()


def _run_creator(count: int, proxy: Optional[str]):
    global _creator_state
    with _creator_lock:
        _creator_state["status"] = "running"
        _creator_state["logs"] = ["Starting account creator..."]
        _creator_state["created_accounts"] = []
    
    def log(msg):
        print(msg)
        with _creator_lock:
            _creator_state["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            if len(_creator_state["logs"]) > 100:
                _creator_state["logs"].pop(0)

    try:
        import account_creator
        import time
        log(f"Configured to create {count} accounts.")
        if proxy:
            log(f"Using proxy: {proxy.split('@')[-1] if '@' in proxy else proxy}")
        else:
            log("No proxy configured — direct connection.")

        for i in range(1, count + 1):
            log(f"Starting creation of account {i} of {count}...")
            try:
                res = account_creator.create_one_account(proxy=proxy)
                with _creator_lock:
                    _creator_state["created_accounts"].append(res)
                log(f"Successfully created and logged account {i}: {res['user_id']}")
            except Exception as e:
                log(f"Failed to create account {i}: {e}")
            
            if i < count:
                log("Sleeping 10 seconds before starting next account...")
                time.sleep(10)
                
        with _creator_lock:
            _creator_state["status"] = "success"
    except Exception as e:
        log(f"Fatal error in account creator thread: {e}")
        with _creator_lock:
            _creator_state["status"] = "error"


@app.post("/create-accounts", tags=["Account Creator"], summary="Create multiple BuyCrash accounts automatically")
def create_accounts(count: int = 6, x_api_key: str = Header(default="")):
    _auth(x_api_key)
    global _creator_state
    
    # 1. Check if scraper script is running
    with _lock:
        if _state["status"] == "running":
            raise HTTPException(status_code=400, detail="scraper script is currently running; stop it first to prevent conflicts.")

    # 2. Check if another account creation is already running
    with _creator_lock:
        if _creator_state["status"] == "running":
            raise HTTPException(status_code=400, detail="An account creation job is already running.")

    # 3. Load proxy from sheets config B24
    # cfg = sheets_handler.load_config()
    # proxy = cfg.get("residential_proxy")
    proxy = None

    # 4. Trigger creation in background thread
    threading.Thread(target=_run_creator, args=(count, proxy), daemon=True).start()
    return {"message": f"Started creation of {count} accounts in background. Call GET /create-accounts/status to monitor."}


@app.get("/create-accounts/status", tags=["Account Creator"], summary="Check status of background account creation")
def create_accounts_status(x_api_key: str = Header(default="")):
    _auth(x_api_key)
    with _creator_lock:
        return dict(_creator_state)

"""
recheck additions
"""

_recheck_state = {
    "status"       : "idle",      # idle | running | stopped | error
    "started_at"   : None,
    "stopped_at"   : None,
    "exit_code"    : None,
    "found_count"  : 0,
    "searches_done": 0,
    "log_tail"     : [],
}
_recheck_lock   = threading.Lock()
_recheck_thread = None


def _run_recheck_thread():
    """Background thread that runs the full recheck cycle."""
    import sheets_handler
    import recheck_runner

    log_lines = []

    def _capture(msg: str):
        print(msg)
        with _recheck_lock:
            log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            if len(log_lines) > 100:
                log_lines.pop(0)
            _recheck_state["log_tail"] = list(log_lines)

    _capture("Loading config for recheck...")
    try:
        cfg = sheets_handler.load_config()
        cfg.update(sheets_handler.load_recheck_config())
    except Exception as e:
        _capture(f"Config load failed: {e}")
        with _recheck_lock:
            _recheck_state["status"]     = "error"
            _recheck_state["stopped_at"] = datetime.now().isoformat()
        return

    _capture(f"Starting recheck — {len(cfg.get('recheck_accounts', []))} accounts, "
             f"limit={cfg.get('recheck_daily_limit', 200)}")

    try:
        outcome = recheck_runner.run_recheck(cfg)
    except Exception as e:
        _capture(f"Recheck crashed: {e}")
        outcome = "crash"

    with _recheck_lock:
        _recheck_state["status"]        = "stopped" if outcome == "done" else outcome
        _recheck_state["stopped_at"]    = datetime.now().isoformat()
        _recheck_state["found_count"]   = recheck_runner._found_count
        _recheck_state["searches_done"] = recheck_runner._searches_done

    _capture(f"Recheck finished: {outcome} | "
             f"found={recheck_runner._found_count} | "
             f"searched={recheck_runner._searches_done}")


# ── 3. Add these endpoints to api.py ─────────────────────────────

# POST /recheck/start
@app.post("/recheck/start", tags=["Recheck"], summary="Start the daily Not Found recheck")
def recheck_start(x_api_key: str = Header(default="")):
    _auth(x_api_key)

    with _lock:
        if _state["status"] == "running":
            raise HTTPException(
                status_code=400,
                detail="Normal search is currently running — stop it first"
            )

    with _recheck_lock:
        if _recheck_state["status"] == "running":
            raise HTTPException(status_code=400, detail="Recheck is already running")
        _recheck_state.update(
            status       = "running",
            started_at   = datetime.now().isoformat(),
            stopped_at   = None,
            exit_code    = None,
            found_count  = 0,
            searches_done= 0,
            log_tail     = [],
        )

    t = threading.Thread(target=_run_recheck_thread, daemon=True)
    t.start()

    return {
        "message"   : "Recheck started",
        "started_at": _recheck_state["started_at"],
    }


# POST /recheck/stop
@app.post("/recheck/stop", tags=["Recheck"], summary="Stop the recheck cleanly via control cell")
def recheck_stop(x_api_key: str = Header(default="")):
    _auth(x_api_key)

    with _recheck_lock:
        if _recheck_state["status"] != "running":
            raise HTTPException(status_code=400, detail="Recheck is not running")

    # Write stop command to the shared control cell B33
    _write_control("stop")

    return {"message": "Stop command sent to recheck (via control cell B33)"}


# GET /recheck/status
@app.get("/recheck/status", tags=["Recheck"],
         summary="Current recheck status, progress, and last 100 log lines")
def recheck_status(x_api_key: str = Header(default="")):
    _auth(x_api_key)

    with _recheck_lock:
        s = dict(_recheck_state)

    if s["status"] == "running" and s["started_at"]:
        sec = (datetime.now() - datetime.fromisoformat(s["started_at"])).total_seconds()
        h, r = divmod(int(sec), 3600)
        m, sc = divmod(r, 60)
        s["uptime"] = f"{h}h {m}m {sc}s"

    return s


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", "5000"))
    print(f"Swagger UI → http://0.0.0.0:{port}/docs")
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=False)