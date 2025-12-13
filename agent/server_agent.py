#!/usr/bin/env python3
import os
import time
import json
import hashlib
import socket
from datetime import datetime, timezone
import requests

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
RULES_PATH = os.path.join(os.path.dirname(__file__), "severity_rules.json")


def load_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return default if default is not None else {}
    except json.JSONDecodeError:
        return default if default is not None else {}


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def load_config():
    return load_json(CONFIG_PATH, {})


def load_rules():
    rules = load_json(RULES_PATH, {})
    # Normalize to lowercase
    normalized = {}
    for level, words in rules.items():
        normalized[level.upper()] = [w.lower() for w in words]
    return normalized


def classify_severity(message, rules):
    m = (message or "").lower()
    # highest first
    for level in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        if level in rules:
            for word in rules[level]:
                if word in m:
                    return level
    return "INFO"


def iso_utc_now():
    return datetime.now(timezone.utc).isoformat()


def detect_ip_from_line(line: str):
    # very naive IP detection, good enough as a hint
    for part in line.split():
        if part.count(".") == 3:
            return part
    return None


def build_watch_file_list(logs_dir, log_files):
    """
    Build a set of absolute file paths to watch.

    - logs_dir: optional directory to scan for all regular files directly inside
    - log_files: optional list of specific files (absolute or relative)
      - if relative, join with logs_dir if logs_dir is given,
        otherwise resolve relative to current working dir.
    """
    paths = set()

    # Add all files in logs_dir (non-recursive)
    if logs_dir:
        if os.path.isdir(logs_dir):
            for fname in sorted(os.listdir(logs_dir)):
                fpath = os.path.join(logs_dir, fname)
                if os.path.isfile(fpath):
                    paths.add(os.path.abspath(fpath))
        else:
            print(f"[server_agent] logs_dir '{logs_dir}' is not a directory or does not exist")

    # Add explicit files
    for p in log_files or []:
        if not p:
            continue
        # If path is not absolute, try relative to logs_dir first, else cwd
        if not os.path.isabs(p):
            if logs_dir:
                candidate = os.path.join(logs_dir, p)
            else:
                candidate = os.path.abspath(p)
        else:
            candidate = p

        candidate = os.path.abspath(candidate)
        if os.path.isfile(candidate):
            paths.add(candidate)
        else:
            # Don't spam too hard; just log once per loop if missing
            print(f"[server_agent] configured log file missing: {candidate}")

    return sorted(paths)


def tail_files(file_paths, state_path, rules, host, source_name):
    """
    Tails all files in file_paths, remembering offsets in state_path.
    Returns list of log dicts ready to send.
    """
    state = load_json(state_path, {})
    results = []
    hostname = host or socket.gethostname()

    for fpath in file_paths:
        last_pos = state.get(fpath, 0)
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(last_pos)
                line_index = 0
                for line in f:
                    line = line.rstrip("\n")
                    if not line.strip():
                        continue

                    severity = classify_severity(line, rules)
                    ts = iso_utc_now()
                    meta = {}

                    ip = detect_ip_from_line(line)
                    if ip:
                        meta["ip"] = ip

                    results.append({
                        "source_name": source_name,
                        "host": hostname,
                        "file_path": fpath,
                        "line_number": line_index,
                        "timestamp": ts,
                        "severity": severity,
                        "tags": [],
                        "message": line,
                        "meta": meta
                    })
                    line_index += 1

                state[fpath] = f.tell()
        except FileNotFoundError:
            # file might appear later; don't kill the loop
            print(f"[server_agent] file not found (yet): {fpath}")
        except PermissionError:
            print(f"[server_agent] permission denied reading: {fpath}")
        except Exception as e:
            print(f"[server_agent] Error reading {fpath}: {e}")

    save_json(state_path, state)
    return results


def send_logs(config, logs):
    if not logs:
        return

    url = config["backend_url"].rstrip("/") + "/api/logs/bulk"
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": config["api_key"]
    }
    payload = {
        "source_type": "server",
        "logs": logs
    }
    try:
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        r.raise_for_status()
        print(f"[server_agent] Sent {len(logs)} logs")
    except Exception as e:
        print(f"[server_agent] Failed to send logs: {e}")


def main():
    config = load_config()
    rules = load_rules()
    sa = config.get("server_agent", {})

    logs_dir = sa.get("logs_dir") or None
    log_files = sa.get("log_files") or []

    state_path = os.path.join(
        os.path.dirname(__file__),
        sa.get("state_file", "server_agent_state.json")
    )
    host = sa.get("host") or socket.gethostname()
    source_name = sa.get("source_name", "server-logs")
    poll_interval = int(sa.get("poll_interval_seconds", 3))

    print(f"[server_agent] Host: {host}")
    print(f"[server_agent] logs_dir: {logs_dir!r}")
    print(f"[server_agent] log_files: {log_files!r}")

    while True:
        try:
            files_to_watch = build_watch_file_list(logs_dir, log_files)
            if not files_to_watch:
                print("[server_agent] No files to watch (check logs_dir/log_files config)")
            else:
                logs = tail_files(files_to_watch, state_path, rules, host, source_name)
                if logs:
                    send_logs(config, logs)
        except Exception as e:
            print(f"[server_agent] Loop error: {e}")
        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
