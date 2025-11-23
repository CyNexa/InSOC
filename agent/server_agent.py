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


def tail_files(logs_dir, state_path, rules, host, source_name):
  """
  Tails all *.log files in logs_dir, remembering offsets in state_path.
  Returns list of log dicts ready to send.
  """
  state = load_json(state_path, {})
  results = []
  hostname = host or socket.gethostname()

  if not os.path.isdir(logs_dir):
    return []

  for fname in sorted(os.listdir(logs_dir)):
    fpath = os.path.join(logs_dir, fname)

    # 🔥 Only touch files that end with `.log`
    if not os.path.isfile(fpath):
      continue
    if not fname.endswith(".log"):
      continue

    last_pos = state.get(fpath, 0)
    try:
      with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
        f.seek(last_pos)
        line_number = 0
        # We don't know original line number; we can track offset only
        # But to keep unique index meaningful, we still track incremental offset lines
        # We'll recompute from current chunk
        for line in f:
          line = line.rstrip("\n")
          if not line.strip():
            continue
          severity = classify_severity(line, rules)
          ts = iso_utc_now()
          meta = {}

          # From log content, attempt to extract IP (super basic)
          # you can improve by regex later
          ip = None
          parts = line.split()
          for p in parts:
            if p.count(".") == 3:
              ip = p
              break
          if ip:
            meta["ip"] = ip

          results.append({
            "source_name": source_name,
            "host": hostname,
            "file_path": fpath,
            "line_number": line_number,
            "timestamp": ts,
            "severity": severity,
            "tags": [],
            "message": line,
            "meta": meta
          })
          line_number += 1

        state[fpath] = f.tell()
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
  logs_dir = sa.get("logs_dir", "/Logs")
  state_path = os.path.join(os.path.dirname(__file__), sa.get("state_file", "server_agent_state.json"))
  host = sa.get("host") or socket.gethostname()
  source_name = sa.get("source_name", "server-logs")
  poll_interval = int(sa.get("poll_interval_seconds", 3))

  print(f"[server_agent] Watching {logs_dir} on host {host}")

  while True:
    try:
      logs = tail_files(logs_dir, state_path, rules, host, source_name)
      if logs:
        send_logs(config, logs)
    except Exception as e:
      print(f"[server_agent] Loop error: {e}")
    time.sleep(poll_interval)


if __name__ == "__main__":
  main()
