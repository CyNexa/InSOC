#!/usr/bin/env python3
import os
import time
import json
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


def iso_utc_now():
  return datetime.now(timezone.utc).isoformat()


def tail_text_file(path, last_pos):
  if not os.path.isfile(path):
    return [], last_pos

  lines = []
  try:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
      f.seek(last_pos)
      for line in f:
        lines.append(line.rstrip("\n"))
      new_pos = f.tell()
  except Exception:
    return [], last_pos
  return lines, new_pos


def collect_logs(config, rules, state, hostname, source_name):
  """
  Collects client log files.
  """
  ca = config.get("client_agent", {})
  logs_files = ca.get("logs_files", [])
  results = []
  for path in logs_files:
    last_pos = state.get(f"log:{path}", 0)
    lines, new_pos = tail_text_file(path, last_pos)
    if new_pos != last_pos:
      state[f"log:{path}"] = new_pos

    ln = 0
    for line in lines:
      if not line.strip():
        continue
      severity = classify_severity(line, rules)
      ts = iso_utc_now()
      meta = {}
      # very rough IP detection
      ip = None
      for part in line.split():
        if part.count(".") == 3:
          ip = part
          break
      if ip:
        meta["ip"] = ip

      results.append({
        "source_name": source_name,
        "host": hostname,
        "file_path": path,
        "line_number": ln,
        "timestamp": ts,
        "severity": severity,
        "tags": [],
        "message": line,
        "meta": meta
      })
      ln += 1

  return results


def collect_commands(config, rules, state, hostname, user):
  """
  Collects new lines from bash_history as command_history.
  """
  ca = config.get("client_agent", {})
  hist_path = ca.get("bash_history_path")
  if not hist_path:
    return []

  last_pos = state.get("bash_history_pos", 0)
  lines, new_pos = tail_text_file(hist_path, last_pos)
  if new_pos != last_pos:
    state["bash_history_pos"] = new_pos

  commands = []
  for line in lines:
    cmd = line.strip()
    if not cmd:
      continue
    severity = "INFO"
    # simple suspicious check
    lower = cmd.lower()
    if any(x in lower for x in ["nmap", "netcat", "nc ", "chmod 777", "rm -rf", "wget http", "curl http"]):
      severity = "HIGH"
    elif any(x in lower for x in ["sudo", "apt install", "systemctl", "chown"]):
      severity = "MEDIUM"

    commands.append({
      "host": hostname,
      "user": user,
      "command": cmd,
      "timestamp": iso_utc_now(),
      "severity": severity,
      "meta": {}
    })

  return commands


def send_logs(config, logs):
  if not logs:
    return

  url = config["backend_url"].rstrip("/") + "/api/logs/bulk"
  headers = {
    "Content-Type": "application/json",
    "X-API-KEY": config["api_key"]
  }
  payload = {
    "source_type": "client",
    "logs": logs
  }
  try:
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
    r.raise_for_status()
    print(f"[client_agent] Sent {len(logs)} logs")
  except Exception as e:
    print(f"[client_agent] Failed to send logs: {e}")


def send_commands(config, commands):
  if not commands:
    return

  url = config["backend_url"].rstrip("/") + "/api/commands/bulk"
  headers = {
    "Content-Type": "application/json",
    "X-API-KEY": config["api_key"]
  }
  payload = {
    "source_type": "client",
    "commands": commands
  }
  try:
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
    r.raise_for_status()
    print(f"[client_agent] Sent {len(commands)} commands")
  except Exception as e:
    print(f"[client_agent] Failed to send commands: {e}")


def main():
  config = load_config()
  rules = load_rules()
  ca = config.get("client_agent", {})
  state_path = os.path.join(os.path.dirname(__file__), ca.get("state_file", "client_agent_state.json"))
  state = load_json(state_path, {})
  hostname = ca.get("host") or socket.gethostname()
  source_name = ca.get("source_name", "client-logs")
  user = ca.get("user") or os.getenv("USER") or "unknown"
  poll_interval = int(ca.get("poll_interval_seconds", 5))

  print(f"[client_agent] Running on host {hostname}, user={user}")

  while True:
    try:
      logs = collect_logs(config, rules, state, hostname, source_name)
      commands = collect_commands(config, rules, state, hostname, user)
      if logs:
        send_logs(config, logs)
      if commands:
        send_commands(config, commands)
      save_json(state_path, state)
    except Exception as e:
      print(f"[client_agent] Loop error: {e}")
    time.sleep(poll_interval)


if __name__ == "__main__":
  main()
