// backend/src/routes/api_logs.js
const express = require("express");
const router = express.Router();
const db = require("../db");
const crypto = require("crypto");
const { verifyApiKey } = require("../authMiddleware");

// API: ingest logs (bulk)
router.post("/api/logs/bulk", verifyApiKey, (req, res) => {
  const { source_type, logs } = req.body;
  if (!source_type || !logs || !Array.isArray(logs)) {
    return res.status(400).json({ error: "Invalid payload" });
  }

  const insert = db.prepare(`
    INSERT OR IGNORE INTO logs 
    (source_type, source_name, host, file_path, line_number, timestamp, severity, tags, message, message_hash, meta)
    VALUES (@source_type, @source_name, @host, @file_path, @line_number, @timestamp, @severity, @tags, @message, @message_hash, @meta)
  `);

  const insertMany = db.transaction((rows) => {
    for (const row of rows) {
      insert.run(row);
    }
  });

  const payload = [];
  for (const l of logs) {
    if (!l.message || !l.timestamp) continue;
    const messageHash = crypto
      .createHash("sha1")
      .update(String(l.message))
      .digest("hex");

    payload.push({
      source_type,
      source_name: l.source_name || null,
      host: l.host || null,
      file_path: l.file_path || null,
      line_number:
        typeof l.line_number === "number" ? l.line_number : null,
      timestamp: l.timestamp,
      severity: l.severity || "INFO",
      tags: l.tags ? JSON.stringify(l.tags) : null,
      message: l.message,
      message_hash: messageHash,
      meta: l.meta ? JSON.stringify(l.meta) : null,
    });
  }

  if (payload.length > 0) {
    insertMany(payload);
  }

  const io = req.app.get("io");
  if (io && payload.length > 0) {
    const lastInserted = db
      .prepare(
        "SELECT * FROM logs ORDER BY datetime(timestamp) DESC LIMIT 50"
      )
      .all();
    io.emit("log:new", lastInserted);
  }

  return res.json({ ok: true, inserted: payload.length });
});

module.exports = router;
