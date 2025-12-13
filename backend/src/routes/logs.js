const express = require("express");
const router = express.Router();
const db = require("../db");
const crypto = require("crypto");
const { verifyApiKey } = require("../authMiddleware");

// Helper: convert UTC to IST string without timezone label
function toISTString(utcIsoString) {
  const date = new Date(utcIsoString);
  return date.toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });
}

// Dashboard
router.get("/dashboard", (req, res) => {
  const total = db.prepare("SELECT COUNT(*) as c FROM logs").get().c;
  const bySeverity = db
    .prepare(
      "SELECT severity, COUNT(*) as c FROM logs GROUP BY severity ORDER BY c DESC"
    )
    .all();
  const recentLogs = db
    .prepare(
      "SELECT * FROM logs ORDER BY datetime(timestamp) DESC LIMIT 100"
    )
    .all();

  res.render("dashboard", {
    user: req.session.user,
    total,
    bySeverity,
    recentLogs,
    toISTString,
  });
});

// Server logs page
router.get("/server/logs", (req, res) => {
  const logs = db
    .prepare(
      "SELECT * FROM logs WHERE source_type = 'server' ORDER BY datetime(timestamp) DESC LIMIT 200"
    )
    .all();

  res.render("server_logs", {
    user: req.session.user,
    logs,
    toISTString,
  });
});

// Client logs page
router.get("/client/logs", (req, res) => {
  const logs = db
    .prepare(
      "SELECT * FROM logs WHERE source_type = 'client' ORDER BY datetime(timestamp) DESC LIMIT 200"
    )
    .all();

  res.render("client_logs", {
    user: req.session.user,
    logs,
    toISTString,
  });
});

// API: fetch old logs
router.get("/api/logs", (req, res) => {
  const { before, source_type } = req.query;
  let query =
    "SELECT * FROM logs WHERE 1=1 ";
  const params = {};

  if (source_type === "server" || source_type === "client") {
    query += "AND source_type = @source_type ";
    params.source_type = source_type;
  }

  if (before) {
    query += "AND datetime(timestamp) < datetime(@before) ";
    params.before = before;
  }

  query += "ORDER BY datetime(timestamp) DESC LIMIT 200";

  const rows = db.prepare(query).all(params);
  return res.json({ logs: rows });
});

module.exports = router;
