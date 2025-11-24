#!/usr/bin/env python3
import os
import glob
import time
import json
import socket
import threading
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import hashlib
import requests

BASE_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
RULES_PATH = os.path.join(BASE_DIR, "severity_rules.json")


# ---------- helpers for config / state / time ----------

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


def iso_utc_now():
    return datetime.now(timezone.utc).isoformat()


def hash_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except FileNotFoundError:
        return None


# ---------- severity / rules ----------

def load_rules():
    rules = load_json(RULES_PATH, {})
    normalized = {}
    for level, words in rules.items():
        normalized[level.upper()] = [w.lower() for w in words]
    return normalized


def classify_severity(message, rules):
    m = (message or "").lower()
    for level in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        if level in rules:
            for word in rules[level]:
                if word in m:
                    return level
    return "INFO"


def detect_ip_from_line(line: str):
    for part in line.split():
        if part.count(".") == 3:
            return part
    return None


# ---------- global state ----------

CONFIG = load_json(CONFIG_PATH, {})
RULES = load_rules()
CA = CONFIG.get("client_agent", {})

STATE_PATH = os.path.join(BASE_DIR, CA.get("state_file", "client_agent_state.json"))
STATE = load_json(STATE_PATH, {})

HOSTNAME = CA.get("host") or socket.gethostname()
SOURCE_NAME = CA.get("source_name", "client-logs")
USER = CA.get("user") or os.getenv("USER") or "unknown"

BACKEND_URL = CONFIG.get("backend_url", "http://localhost:3000").rstrip("/")
API_KEY = CONFIG.get("api_key", "")

CONTROL_LISTEN = CA.get("control_listen", "0.0.0.0")
CONTROL_PORT = int(CA.get("control_port", 5050))
ACTION_KEY = CA.get("action_key", "change-me")

ANTI_TAMPER_ENABLED = bool(CA.get("anti_tamper_enabled", False))
ANTI_TAMPER_INTERVAL = int(CA.get("anti_tamper_interval_seconds", 15))

# pre-compute hashes for tamper detection
AGENT_HASH = hash_file(os.path.abspath(__file__))
CONFIG_HASH = hash_file(CONFIG_PATH)


STATE_LOCK = threading.Lock()
LOG_SEND_LOCK = threading.Lock()


# ---------- sending to server ----------

def send_logs_to_server(logs):
    if not logs:
        return
    url = BACKEND_URL + "/api/logs/bulk"
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": API_KEY,
    }
    payload = {
        "source_type": "client",
        "logs": logs,
    }
    try:
        with LOG_SEND_LOCK:
            r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        r.raise_for_status()
        print(f"[client_agent] Sent {len(logs)} logs")
    except Exception as e:
        print(f"[client_agent] Failed to send logs: {e}")


def send_commands_to_server(cmds):
    if not cmds:
        return
    url = BACKEND_URL + "/api/commands/bulk"
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": API_KEY,
    }
    payload = {
        "source_type": "client",
        "commands": cmds,
    }
    try:
        with LOG_SEND_LOCK:
            r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        r.raise_for_status()
        print(f"[client_agent] Sent {len(cmds)} commands")
    except Exception as e:
        print(f"[client_agent] Failed to send commands: {e}")


def send_control_log(severity, message, meta=None):
    """
    Use the normal logs API to send a special control log.
    """
    log = {
        "source_name": SOURCE_NAME,
        "host": HOSTNAME,
        "file_path": None,
        "line_number": None,
        "timestamp": iso_utc_now(),
        "severity": severity,
        "tags": ["control", "remote-action"],
        "message": message,
        "meta": meta or {},
    }
    send_logs_to_server([log])


# ---------- log collection ----------

def tail_file(path, key_prefix):
    """
    Tail file from last offset saved in STATE under key_prefix + path.
    Returns (lines, new_offset).
    """
    state_key = f"{key_prefix}:{path}"
    with STATE_LOCK:
        last_pos = STATE.get(state_key, 0)

    lines = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(last_pos)
            for line in f:
                lines.append(line.rstrip("\n"))
            new_pos = f.tell()
    except FileNotFoundError:
        return [], last_pos
    except PermissionError:
        print(f"[client_agent] permission denied for {path}")
        return [], last_pos
    except Exception as e:
        print(f"[client_agent] error reading {path}: {e}")
        return [], last_pos

    with STATE_LOCK:
        STATE[state_key] = new_pos

    return lines, new_pos


def collect_log_files():
    """
    Collect new lines from configured log files.
    """
    log_files = CA.get("log_files") or CA.get("logs_files") or []
    results = []

    for path in log_files:
        lines, _ = tail_file(path, "log")
        ln = 0
        for line in lines:
            if not line.strip():
                continue
            severity = classify_severity(line, RULES)
            ts = iso_utc_now()
            meta = {}
            ip = detect_ip_from_line(line)
            if ip:
                meta["ip"] = ip

            results.append({
                "source_name": SOURCE_NAME,
                "host": HOSTNAME,
                "file_path": path,
                "line_number": ln,
                "timestamp": ts,
                "severity": severity,
                "tags": [],
                "message": line,
                "meta": meta,
            })
            ln += 1

    return results


def collect_bash_history_all():
    """
    Collect new bash history lines from ALL users based on bash_history_globs.
    """
    globs = CA.get("bash_history_globs") or []
    results = []

    for pattern in globs:
        for hist_path in glob.glob(pattern):
            # figure out user from path
            if hist_path == "/root/.bash_history":
                user = "root"
            else:
                # /home/<user>/.bash_history
                parts = hist_path.split(os.sep)
                # ['', 'home', '<user>', '.bash_history']
                user = parts[2] if len(parts) > 3 else "unknown"

            lines, _ = tail_file(hist_path, f"bash_hist:{hist_path}")
            for line in lines:
                cmd = line.strip()
                if not cmd:
                    continue

                severity = "INFO"
                lower = cmd.lower()
                if any(x in lower for x in ["nmap", "netcat", " nc ", "chmod 777", "rm -rf", "wget http", "curl http"]):
                    severity = "HIGH"
                elif any(x in lower for x in ["sudo", "apt install", "systemctl", "chown", "adduser", "useradd"]):
                    severity = "MEDIUM"

                results.append({
                    "host": HOSTNAME,
                    "user": user,
                    "command": cmd,
                    "timestamp": iso_utc_now(),
                    "severity": severity,
                    "meta": {
                        "history_path": hist_path
                    },
                })
    return results


def log_loop():
    poll_interval = int(CA.get("poll_interval_seconds", 5))
    print(f"[client_agent] Log loop started with interval={poll_interval}s")
    global STATE

    while True:
        try:
            logs = collect_log_files()
            cmds = collect_bash_history_all()

            if logs:
                send_logs_to_server(logs)
            if cmds:
                send_commands_to_server(cmds)

            with STATE_LOCK:
                save_json(STATE_PATH, STATE)
        except Exception as e:
            print(f"[client_agent] log loop error: {e}")

        time.sleep(poll_interval)


# ---------- remote actions (shutdown, nuke, etc.) ----------

def run_cmd(cmd_list, ignore_errors=False):
    try:
        print(f"[client_agent] running: {' '.join(cmd_list)}")
        res = subprocess.run(cmd_list, capture_output=True, text=True)
        if res.returncode != 0 and not ignore_errors:
            print(f"[client_agent] command failed: {' '.join(cmd_list)} -> {res.stderr.strip()}")
            return False, res.stderr.strip() or res.stdout.strip()
        return True, res.stdout.strip()
    except Exception as e:
        print(f"[client_agent] exception running command: {e}")
        if ignore_errors:
            return False, str(e)
        return False, str(e)


def change_password(target_user, new_password=None):
    if new_password is None:
        new_password = hashlib.sha256(os.urandom(32)).hexdigest()
    cmd = f"{target_user}:{new_password}"
    ok, err = run_cmd(["sudo", "chpasswd"], ignore_errors=False)
    # Using echo is a bit more complex; we'll use subprocess with input:
    try:
        print(f"[client_agent] changing password for {target_user}")
        p = subprocess.run(
            ["sudo", "chpasswd"],
            input=cmd,
            text=True,
            capture_output=True,
        )
        if p.returncode != 0:
            return False, p.stderr.strip() or p.stdout.strip(), None
        return True, "", new_password
    except Exception as e:
        return False, str(e), None


def block_internet():
    # VERY AGGRESSIVE: drop everything
    ok1, e1 = run_cmd(["sudo", "iptables", "-P", "INPUT", "DROP"], ignore_errors=True)
    ok2, e2 = run_cmd(["sudo", "iptables", "-P", "OUTPUT", "DROP"], ignore_errors=True)
    ok3, e3 = run_cmd(["sudo", "iptables", "-P", "FORWARD", "DROP"], ignore_errors=True)
    return (ok1 and ok2 and ok3), (e1 or e2 or e3)


def unblock_internet():
    ok1, e1 = run_cmd(["sudo", "iptables", "-P", "INPUT", "ACCEPT"], ignore_errors=True)
    ok2, e2 = run_cmd(["sudo", "iptables", "-P", "OUTPUT", "ACCEPT"], ignore_errors=True)
    ok3, e3 = run_cmd(["sudo", "iptables", "-P", "FORWARD", "ACCEPT"], ignore_errors=True)
    return (ok1 and ok2 and ok3), (e1 or e2 or e3)


def shutdown_now():
    # background to not block HTTP response
    run_cmd(["sudo", "shutdown", "-h", "now"], ignore_errors=True)


def reboot_now():
    run_cmd(["sudo", "reboot"], ignore_errors=True)


def perform_nuke(reason="remote_nuke"):
    """
    Nuke sequence:
    - change password (random)
    - block internet
    - send control log
    - shutdown
    """
    target_user = USER
    ok_pw, err_pw, new_pw = change_password(target_user)
    ok_net, err_net = block_internet()

    meta = {
        "action": "NUKE",
        "reason": reason,
        "password_changed": ok_pw,
        "password_user": target_user,
        "password_new": new_pw if ok_pw else None,
        "block_net_ok": ok_net,
        "errors": {
            "password": err_pw,
            "net": err_net,
        },
    }
    send_control_log("CRITICAL", f"NUKE executed on {HOSTNAME}", meta=meta)

    # after log, shutdown
    shutdown_now()


# ---------- anti-tamper thread ----------

def anti_tamper_loop():
    if not ANTI_TAMPER_ENABLED:
        print("[client_agent] Anti-tamper disabled")
        return

    print(f"[client_agent] Anti-tamper enabled (interval={ANTI_TAMPER_INTERVAL}s)")
    while True:
        try:
            current_agent_hash = hash_file(os.path.abspath(__file__))
            current_config_hash = hash_file(CONFIG_PATH)

            tamper = False
            reasons = []

            if AGENT_HASH is not None and current_agent_hash is not None and current_agent_hash != AGENT_HASH:
                tamper = True
                reasons.append("agent_file_changed")

            if CONFIG_HASH is not None and current_config_hash is not None and current_config_hash != CONFIG_HASH:
                tamper = True
                reasons.append("config_file_changed")

            if tamper:
                reason = "anti_tamper:" + ",".join(reasons)
                print(f"[client_agent] TAMPER DETECTED: {reason}")
                send_control_log("CRITICAL", f"Tamper detected on {HOSTNAME}", meta={"reasons": reasons})
                perform_nuke(reason=reason)
                # perform_nuke calls shutdown; we still break loop to be safe
                break

        except Exception as e:
            print(f"[client_agent] anti-tamper error: {e}")

        time.sleep(ANTI_TAMPER_INTERVAL)


# ---------- HTTP control server ----------

class ControlHandler(BaseHTTPRequestHandler):
    server_version = "ClientAgentControl/1.0"

    def log_message(self, fmt, *args):
        # quiet
        return

    def _send(self, code, payload):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_POST(self):
        if self.path != "/api/action":
            return self._send(404, {"error": "not_found"})

        key = self.headers.get("X-ACTION-KEY", "")
        if key != ACTION_KEY:
            return self._send(403, {"error": "forbidden"})

        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = self.rfile.read(length)
            data = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            return self._send(400, {"error": "invalid_json"})

        action = (data.get("action") or "").strip().lower()
        reason = data.get("reason") or ""
        requested_by = data.get("requested_by") or "unknown"

        if not action:
            return self._send(400, {"error": "missing_action"})

        print(f"[client_agent] remote action requested: {action} by {requested_by}, reason={reason}")

        try:
            if action == "shutdown":
                send_control_log("HIGH", f"Remote SHUTDOWN requested by {requested_by}", {"reason": reason})
                self._send(200, {"ok": True, "action": "shutdown"})
                shutdown_now()
                return

            elif action == "reboot":
                send_control_log("HIGH", f"Remote REBOOT requested by {requested_by}", {"reason": reason})
                self._send(200, {"ok": True, "action": "reboot"})
                reboot_now()
                return

            elif action == "block-net":
                ok, err = block_internet()
                send_control_log(
                    "HIGH",
                    f"Remote BLOCK-NET requested by {requested_by}",
                    {"reason": reason, "ok": ok, "error": err},
                )
                return self._send(200, {"ok": ok, "error": err})

            elif action == "unblock-net":
                ok, err = unblock_internet()
                send_control_log(
                    "MEDIUM",
                    f"Remote UNBLOCK-NET requested by {requested_by}",
                    {"reason": reason, "ok": ok, "error": err},
                )
                return self._send(200, {"ok": ok, "error": err})

            elif action == "change-password":
                target_user = data.get("target_user") or USER
                new_password = data.get("new_password")  # optional; if missing, random
                ok, err, pw = change_password(target_user, new_password)
                meta = {
                    "reason": reason,
                    "requested_by": requested_by,
                    "target_user": target_user,
                    "ok": ok,
                    "error": err,
                    "new_password": pw if ok else None,
                }
                send_control_log(
                    "HIGH" if ok else "MEDIUM",
                    f"Remote CHANGE-PASSWORD executed for {target_user} by {requested_by}",
                    meta,
                )
                return self._send(200, {"ok": ok, "error": err, "new_password": pw if ok else None})

            elif action == "nuke":
                send_control_log(
                    "CRITICAL",
                    f"Remote NUKE requested by {requested_by}",
                    {"reason": reason},
                )
                self._send(200, {"ok": True, "action": "nuke"})
                perform_nuke(reason=reason or f"remote_nuke_by:{requested_by}")
                return

            else:
                return self._send(400, {"error": "unknown_action", "action": action})

        except Exception as e:
            print(f"[client_agent] error handling action {action}: {e}")
            return self._send(500, {"error": "internal_error", "detail": str(e)})


def control_server_loop():
    addr = (CONTROL_LISTEN, CONTROL_PORT)
    httpd = HTTPServer(addr, ControlHandler)
    print(f"[client_agent] Control API listening on {CONTROL_LISTEN}:{CONTROL_PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[client_agent] control server error: {e}")
    finally:
        httpd.server_close()


# ---------- main ----------

def main():
    print(f"[client_agent] Starting on host={HOSTNAME}, user={USER}")
    print(f"[client_agent] Backend URL: {BACKEND_URL}")
    print(f"[client_agent] Control listen: {CONTROL_LISTEN}:{CONTROL_PORT}")
    print(f"[client_agent] Anti-tamper: {ANTI_TAMPER_ENABLED}")

    # threads
    t_logs = threading.Thread(target=log_loop, daemon=True)
    t_logs.start()

    if ANTI_TAMPER_ENABLED:
        t_tamper = threading.Thread(target=anti_tamper_loop, daemon=True)
        t_tamper.start()

    # control server (blocking)
    control_server_loop()


if __name__ == "__main__":
    main()
