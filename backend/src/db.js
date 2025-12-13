const Database = require("better-sqlite3");
const path = require("path");
require("dotenv").config();

const dbPath = process.env.DB_PATH
  ? path.isAbsolute(process.env.DB_PATH)
    ? process.env.DB_PATH
    : path.join(__dirname, "..", process.env.DB_PATH)
  : path.join(__dirname, "..", "data", "soc.db");

const db = new Database(dbPath);
db.pragma("journal_mode = WAL");

// Schema
db.exec(`
CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_type TEXT NOT NULL,         -- 'server' or 'client'
  source_name TEXT,
  host TEXT,
  file_path TEXT,
  line_number INTEGER,
  timestamp TEXT NOT NULL,           -- ISO string UTC
  severity TEXT NOT NULL,
  tags TEXT,                         -- JSON array as string
  message TEXT NOT NULL,
  message_hash TEXT,
  meta TEXT                          -- JSON object as string
);

CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_severity ON logs(severity);
CREATE INDEX IF NOT EXISTS idx_logs_source ON logs(source_type, host);

CREATE UNIQUE INDEX IF NOT EXISTS idx_logs_unique
ON logs (source_type, host, file_path, line_number, timestamp, message_hash);

CREATE TABLE IF NOT EXISTS command_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_type TEXT NOT NULL,         -- 'server' or 'client'
  host TEXT,
  user TEXT,
  command TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  severity TEXT,
  meta TEXT
);

CREATE INDEX IF NOT EXISTS idx_cmd_host_time ON command_history(host, timestamp);

CREATE TABLE IF NOT EXISTS blocks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ip TEXT NOT NULL,
  source_type TEXT NOT NULL,      -- 'server' or 'client' (where it was triggered)
  reason TEXT,
  block_type TEXT NOT NULL,       -- 'SOFT' or 'HARD'
  status TEXT NOT NULL,           -- 'PENDING','ACTIVE','EXPIRED','FAILED'
  created_at TEXT NOT NULL,
  expires_at TEXT,
  trigger_log_id INTEGER,
  who_triggered TEXT,
  error TEXT
);

CREATE INDEX IF NOT EXISTS idx_blocks_ip ON blocks(ip);
CREATE INDEX IF NOT EXISTS idx_blocks_status ON blocks(status);
`);

module.exports = db;
