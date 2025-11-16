#!/usr/bin/env python3
"""
log_collector_multi.py

- Tail multiple files (handles rotation by inode).
- Shared buffer, batch POST to backend, spool-on-fail.
- Each event contains source path + tiny meta (ip/user).
- Config via optional JSON file passed as first arg, otherwise uses built-in defaults.
- Dependencies: requests (pip install requests)

Usage:
  python3 log_collector_multi.py                # uses defaults
  python3 log_collector_multi.py config.json    # load overrides from JSON
"""

import os
import sys
import time
import json
import signal
import socket
import re
import uuid
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
import requests

# ----------------------
# Built-in defaults (override with config JSON)
# ----------------------
DEFAULT_CONFIG = {
    "LOG_PATHS": [
        "/var/log/auth.log",
        "/var/log/syslog",
        "/var/log/kern.log",
        "/var/log/nginx/access.log",
        "/var/log/nginx/error.log",
        "/var/log/mysql/error.log",
        "/var/log/ufw.log"
    ],
    "BACKEND_URL": "http://127.0.0.1:5050/ingest",
    # "API_TOKEN": None,
    "BATCH_SIZE": 25,
    "FLUSH_INTERVAL": 2.0,
    "SPOOL_DIR": "/var/spool/log_collector",
    "MAX_SPOOL_BYTES": 200 * 1024 * 1024,
    "CONNECT_TIMEOUT": 3.0,
    "REQUEST_TIMEOUT": 5.0,
    "LOG_FILE": "/var/log/log_collector.log",
    "HOSTNAME": socket.gethostname(),
}
# ----------------------

# quick regexes
IP_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.){3}(?:25[0-5]|2[0-4]\d|1?\d{1,2})\b")
USER_RE = re.compile(r"(?:user=|for user |user )([A-Za-z0-9_\-\.]+)")

# runtime state filled after config load
_cfg: Dict[str, Any] = {}
_buffer_lock = threading.Lock()
_buffer: List[Dict[str, Any]] = []
_last_flush = time.time()
_shutdown = threading.Event()

def load_config(path: str = None):
    cfg = DEFAULT_CONFIG.copy()
    if path:
        try:
            with open(path, "r") as fh:
                usercfg = json.load(fh)
            cfg.update(usercfg)
            print(f"Loaded config from {path}")
        except Exception as e:
            print(f"Failed to load config {path}: {e}. Using defaults.")
    return cfg

def log_setup():
    # ensure spool dir exists
    Path(_cfg["SPOOL_DIR"]).mkdir(parents=True, exist_ok=True)
    # ensure log file parent exists
    p = Path(_cfg["LOG_FILE"])
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

def log(msg: str):
    ts = datetime.utcnow().isoformat() + "Z"
    line = f"{ts} {msg}"
    try:
        with open(_cfg["LOG_FILE"], "a") as f:
            f.write(line + "\n")
    except Exception:
        print("LOGERR:", line)
    # always print to stdout (helpful during testing)
    print(line)

def extract_meta(line: str):
    ip_m = IP_RE.search(line)
    user_m = USER_RE.search(line)
    return {
        "ip": ip_m.group(0) if ip_m else None,
        "user": user_m.group(1) if user_m else None,
    }

def make_event(line: str, source: str):
    return {
        "client_uuid": str(uuid.uuid4()),
        "ts": int(time.time()),
        "source": source,
        "msg": line,
        "meta": extract_meta(line),
        "collector": {"host": _cfg.get("HOSTNAME")}
    }

def spool_batch(batch: List[Dict[str,Any]]):
    try:
        total_spool = sum(p.stat().st_size for p in Path(_cfg["SPOOL_DIR"]).glob("*") if p.is_file())
        if total_spool > _cfg["MAX_SPOOL_BYTES"]:
            log(f"SPOOL skipped: spool size {total_spool} > {_cfg['MAX_SPOOL_BYTES']}")
            return
    except Exception:
        pass
    fname = Path(_cfg["SPOOL_DIR"]) / f"batch-{int(time.time())}-{uuid.uuid4().hex}.json"
    try:
        with open(fname, "w") as fh:
            json.dump(batch, fh)
        log(f"Spooled batch -> {fname}")
    except Exception as e:
        log(f"Failed to spool batch: {e}")

def send_batch_http(batch: List[Dict[str,Any]]) -> bool:
    headers = {"Content-Type": "application/json"}
    if _cfg.get("API_TOKEN"):
        headers["Authorization"] = f"Bearer {_cfg['API_TOKEN']}"
    payload = {"events": batch}
    try:
        resp = requests.post(_cfg["BACKEND_URL"], json=payload, headers=headers,
                             timeout=(_cfg["CONNECT_TIMEOUT"], _cfg["REQUEST_TIMEOUT"]))
        if resp.status_code in (200,201,202):
            return True
        else:
            log(f"HTTP {resp.status_code} on send: {resp.text[:200]}")
            return False
    except requests.RequestException as e:
        log(f"HTTP send exception: {e}")
        return False

def flush_spool_once():
    files = sorted([p for p in Path(_cfg["SPOOL_DIR"]).iterdir() if p.is_file()], key=lambda p: p.stat().st_mtime)
    for f in files:
        try:
            with open(f, "r") as fh:
                batch = json.load(fh)
            success = send_batch_http(batch)
            if success:
                f.unlink()
                log(f"Flushed spool file {f}")
            else:
                log(f"Failed to flush spool file {f}; will retry later")
                return False
        except Exception as e:
            log(f"Error reading spool file {f}: {e} - removing corrupt file")
            try:
                f.unlink()
            except Exception:
                pass
    return True

def attempt_flush_buffer(force=False):
    global _last_flush
    with _buffer_lock:
        if not _buffer:
            return
        if (not force) and len(_buffer) < _cfg["BATCH_SIZE"] and (time.time() - _last_flush) < _cfg["FLUSH_INTERVAL"]:
            return
        batch = _buffer[:]
        _buffer.clear()
    # flush spool first
    flush_spool_once()
    ok = send_batch_http(batch)
    if not ok:
        spool_batch(batch)
    else:
        log(f"Sent batch size={len(batch)}")
    _last_flush = time.time()

def queue_line(line: str, source: str):
    ev = make_event(line, source)
    with _buffer_lock:
        _buffer.append(ev)

def follow(path: str):
    """
    Generator that yields new lines from a file and reopens on rotation (inode change).
    """
    try:
        fh = open(path, "r")
    except FileNotFoundError:
        log(f"{path} not found; waiting for it to appear...")
        while not _shutdown.is_set():
            time.sleep(2)
            if os.path.exists(path):
                break
        try:
            fh = open(path, "r")
        except Exception as e:
            log(f"Failed to open {path} after wait: {e}")
            return

    fh.seek(0, os.SEEK_END)
    try:
        current_inode = os.fstat(fh.fileno()).st_ino
    except Exception:
        current_inode = None

    while not _shutdown.is_set():
        line = fh.readline()
        if line:
            yield line.rstrip("\n")
            continue
        time.sleep(0.2)
        # check rotation by inode change
        try:
            stat = os.stat(path)
            if current_inode is not None and stat.st_ino != current_inode:
                log(f"Detected rotation on {path}; reopening.")
                try:
                    new_fh = open(path, "r")
                    fh.close()
                    fh = new_fh
                    current_inode = os.fstat(fh.fileno()).st_ino
                    fh.seek(0, os.SEEK_END)
                except Exception as e:
                    log(f"Failed to reopen {path}: {e}")
                    time.sleep(1)
        except FileNotFoundError:
            # file gone temporarily
            time.sleep(1)
            continue

def follower_thread(path: str):
    log(f"Starting follower for {path}")
    try:
        for line in follow(path):
            if _shutdown.is_set():
                break
            queue_line(line, path)
    except Exception as e:
        log(f"Follower error for {path}: {e}")
    finally:
        log(f"Follower for {path} exiting.")

def background_flusher():
    while not _shutdown.is_set():
        try:
            attempt_flush_buffer(force=False)
            # attempt spool flush periodically
            if int(time.time()) % 30 == 0:
                flush_spool_once()
        except Exception as e:
            log(f"Flusher error: {e}")
        time.sleep(0.5)
    # final flush
    attempt_flush_buffer(force=True)
    flush_spool_once()

def shutdown_handler(signum, frame):
    log(f"Received signal {signum}; shutting down.")
    _shutdown.set()

def main():
    global _cfg
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else None
    _cfg = load_config(cfg_path)
    log_setup()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    flusher = threading.Thread(target=background_flusher, daemon=True)
    flusher.start()

    threads = []
    for p in _cfg["LOG_PATHS"]:
        t = threading.Thread(target=follower_thread, args=(p,), daemon=True)
        t.start()
        threads.append(t)

    log(f"Collector started. following: {', '.join(_cfg['LOG_PATHS'])} -> {_cfg['BACKEND_URL']}")

    try:
        while not _shutdown.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        _shutdown.set()
    finally:
        log("Shutting down; waiting for threads to finish.")
        for t in threads:
            t.join(timeout=2)
        flusher.join(timeout=5)
        log("Collector stopped.")

if __name__ == "__main__":
    main()

