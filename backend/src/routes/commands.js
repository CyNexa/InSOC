const express = require("express");
const router = express.Router();
const db = require("../db");
const { verifyApiKey } = require("../authMiddleware");

// Helper
function toISTString(utcIsoString) {
  const date = new Date(utcIsoString);
  return date.toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });
}

// UI: Server commands
router.get("/server/commands", (req, res) => {
  const rows = db
    .prepare(
      "SELECT * FROM command_history WHERE source_type = 'server' ORDER BY datetime(timestamp) DESC LIMIT 200"
    )
    .all();

  res.render("server_commands", {
    user: req.session.user,
    commands: rows,
    toISTString,
  });
});

// UI: Client commands
router.get("/client/commands", (req, res) => {
  const rows = db
    .prepare(
      "SELECT * FROM command_history WHERE source_type = 'client' ORDER BY datetime(timestamp) DESC LIMIT 200"
    )
    .all();

  res.render("client_commands", {
    user: req.session.user,
    commands: rows,
    toISTString,
  });
});

// API: ingest command history (bulk)
router.post("/api/commands/bulk", verifyApiKey, (req, res) => {
  const { source_type, commands } = req.body;
  if (!source_type || !Array.isArray(commands)) {
    return res.status(400).json({ error: "Invalid payload" });
  }

  const insert = db.prepare(`
    INSERT INTO command_history
    (source_type, host, user, command, timestamp, severity, meta)
    VALUES (@source_type, @host, @user, @command, @timestamp, @severity, @meta)
  `);

  const insertMany = db.transaction((rows) => {
    for (const row of rows) insert.run(row);
  });

  const payload = [];
  for (const c of commands) {
    if (!c.command || !c.timestamp) continue;
    payload.push({
      source_type,
      host: c.host || null,
      user: c.user || null,
      command: c.command,
      timestamp: c.timestamp,
      severity: c.severity || null,
      meta: c.meta ? JSON.stringify(c.meta) : null,
    });
  }

  insertMany(payload);

  const io = req.app.get("io");
  if (io && payload.length > 0) {
    const last = db
      .prepare(
        "SELECT * FROM command_history ORDER BY datetime(timestamp) DESC LIMIT 50"
      )
      .all();
    io.emit("command:new", last);
  }

  return res.json({ ok: true, inserted: payload.length });
});

module.exports = router;
