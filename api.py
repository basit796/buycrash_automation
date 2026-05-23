"""
api.py — FastAPI with built-in Swagger UI at /docs
"""
import os, subprocess, sys, threading
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

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


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", "5000"))
    print(f"Swagger UI → http://0.0.0.0:{port}/docs")
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=False)