#!/usr/bin/env python3
import os
import time
import sqlite3
import subprocess
from datetime import datetime, timezone
import json

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config():
  try:
    with open(CONFIG_PATH, "r") as f:
      return json.load(f)
  except Exception:
    return {}


def utc_now_iso():
  return datetime.now(timezone.utc).isoformat()


def main():
  config = load_config()
  db_path = config.get("db_path")
  if not db_path:
    raise SystemExit("[firewall_agent] db_path not set in config.json")

  # Resolve relative path
  if not os.path.isabs(db_path):
    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), db_path))

  print(f"[firewall_agent] Using DB at {db_path}")

  while True:
    try:
      conn = sqlite3.connect(db_path)
      conn.row_factory = sqlite3.Row
      cur = conn.cursor()

      # 1) Apply PENDING blocks
      cur.execute("SELECT * FROM blocks WHERE status = 'PENDING'")
      pending = cur.fetchall()
      for row in pending:
        ip = row["ip"]
        block_id = row["id"]
        block_type = row["block_type"]
        print(f"[firewall_agent] Applying {block_type} block for {ip} (id={block_id})")

        try:
          # ufw deny from IP
          # requires firewall_agent to run as root or have passwordless sudo for ufw
          cmd = ["sudo", "ufw", "deny", "from", ip]
          res = subprocess.run(cmd, capture_output=True, text=True)
          if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            print(f"[firewall_agent] ufw error for {ip}: {err}")
            cur.execute(
              "UPDATE blocks SET status='FAILED', error=? WHERE id=?",
              (err, block_id),
            )
          else:
            cur.execute(
              "UPDATE blocks SET status='ACTIVE', error=NULL WHERE id=?",
              (block_id,),
            )
            print(f"[firewall_agent] Block applied for {ip}")
        except Exception as e:
          err = str(e)
          print(f"[firewall_agent] exception for {ip}: {err}")
          cur.execute(
            "UPDATE blocks SET status='FAILED', error=? WHERE id=?",
            (err, block_id),
          )

      conn.commit()

      # 2) Expire SOFT blocks
      now_iso = utc_now_iso()
      cur.execute(
        """
        SELECT * FROM blocks
        WHERE status = 'ACTIVE'
          AND block_type = 'SOFT'
          AND expires_at IS NOT NULL
          AND datetime(expires_at) <= datetime(?)
        """,
        (now_iso,),
      )
      expiring = cur.fetchall()
      for row in expiring:
        ip = row["ip"]
        block_id = row["id"]
        print(f"[firewall_agent] Expiring soft block for {ip} (id={block_id})")
        try:
          # best-effort remove rule:
          cmd = ["sudo", "ufw", "delete", "deny", "from", ip]
          res = subprocess.run(cmd, capture_output=True, text=True)
          if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            print(f"[firewall_agent] ufw delete error for {ip}: {err}")
            cur.execute(
              "UPDATE blocks SET status='FAILED', error=? WHERE id=?",
              (err, block_id),
            )
          else:
            cur.execute(
              "UPDATE blocks SET status='EXPIRED', error=NULL WHERE id=?",
              (block_id,),
            )
            print(f"[firewall_agent] Block expired for {ip}")
        except Exception as e:
          err = str(e)
          print(f"[firewall_agent] exception while expiring {ip}: {err}")
          cur.execute(
            "UPDATE blocks SET status='FAILED', error=? WHERE id=?",
            (err, block_id),
          )

      conn.commit()
      conn.close()

    except Exception as e:
      print(f"[firewall_agent] Loop error: {e}")

    time.sleep(5)


if __name__ == "__main__":
  main()
