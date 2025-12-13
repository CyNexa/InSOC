const express = require("express");
const router = express.Router();
const db = require("../db");
const { verifyApiKey } = require("../authMiddleware");

// Helper: IST time
function toISTString(utcIsoString) {
  const date = new Date(utcIsoString);
  return date.toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });
}

// UI pages

router.get("/server/blocks", (req, res) => {
  const blocks = db
    .prepare(
      "SELECT * FROM blocks WHERE source_type = 'server' ORDER BY datetime(created_at) DESC LIMIT 200"
    )
    .all();

  res.render("server_blocks", {
    user: req.session.user,
    blocks,
    toISTString,
  });
});

router.get("/client/blocks", (req, res) => {
  const blocks = db
    .prepare(
      "SELECT * FROM blocks WHERE source_type = 'client' ORDER BY datetime(created_at) DESC LIMIT 200"
    )
    .all();

  res.render("client_blocks", {
    user: req.session.user,
    blocks,
    toISTString,
  });
});

// UI: create block from dashboard/logs
router.post("/blocks", (req, res) => {
  const { ip, source_type, block_type, reason, trigger_log_id } = req.body;
  if (!ip || !source_type || !block_type) {
    return res.status(400).send("Missing fields");
  }

  const now = new Date();
  const createdAt = now.toISOString();
  let expiresAt = null;

  if (block_type === "SOFT") {
    const exp = new Date(now.getTime() + 10 * 60 * 1000); // 10 min
    expiresAt = exp.toISOString();
  }

  const stmt = db.prepare(`
    INSERT INTO blocks
    (ip, source_type, reason, block_type, status, created_at, expires_at, trigger_log_id, who_triggered, error)
    VALUES (@ip, @source_type, @reason, @block_type, 'PENDING', @created_at, @expires_at, @trigger_log_id, @who_triggered, NULL)
  `);

  stmt.run({
    ip,
    source_type,
    reason: reason || null,
    block_type,
    created_at: createdAt,
    expires_at: expiresAt,
    trigger_log_id: trigger_log_id ? Number(trigger_log_id) : null,
    who_triggered: req.session.user
      ? `ADMIN:${req.session.user.username}`
      : "ADMIN:unknown",
  });

  // redirect back
  if (source_type === "server") {
    return res.redirect("/server/blocks");
  } else {
    return res.redirect("/client/blocks");
  }
});

// (Optional) API for agents if needed later (not used by firewall agent since it reads DB directly)
router.get("/api/blocks/pending", (req, res) => {
  const rows = db
    .prepare(
      "SELECT * FROM blocks WHERE status = 'PENDING' ORDER BY datetime(created_at) ASC LIMIT 100"
    )
    .all();
  return res.json({ blocks: rows });
});

// API: update block status (in case you want HTTP control later)
router.post("/api/blocks/:id/status", verifyApiKey, (req, res) => {
  const { id } = req.params;
  const { status, error } = req.body;
  const stmt = db.prepare(
    "UPDATE blocks SET status = @status, error = @error WHERE id = @id"
  );
  stmt.run({
    id: Number(id),
    status,
    error: error || null,
  });
  return res.json({ ok: true });
});

module.exports = router;
