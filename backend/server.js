// server.js
// Simple Express + Socket.IO backend.
// - Accepts POST /ingest { events: [...] }
// - Persists to SQLite (WAL)
// - Broadcasts new events to connected websocket clients
// - Supports replay on WS connect (client sends { type: 'hello', lastSeenId: N })
// - GET /events?after_id=N endpoint for HTTP catch-up
// - POST /block { who, reason } calls a local script (must be configured)

const express = require("express");
const http = require("http");
const { Server } = require("socket.io");
const sqlite3 = require("sqlite3").verbose();
const bodyParser = require("body-parser");
const helmet = require("helmet");
const { execFile } = require("child_process");
const path = require("path");

// ------------- CONFIG -------------
const PORT = process.env.PORT || 5050;
const DB_PATH = process.env.DB_PATH || "./events.sqlite";
const INGEST_TOKEN = ""; // token for agents
const UI_TOKEN = process.env.UI_TOKEN || null; // optional token for UI actions (block)
const BLOCK_SCRIPT = process.env.BLOCK_SCRIPT || "/usr/local/bin/block_ip.sh"; // must exist & be executable
// ----------------------------------

// Express + Socket.IO
const app = express();
const server = http.createServer(app);
const io = new Server(server, {
    cors: { origin: "*" }
});

app.get("/", (req, res) => {
    res.sendFile(path.join(__dirname, "public", "ui.html"));
});
app.use(helmet());
app.use(bodyParser.json({ limit: "2mb" }));

// --- DB init ---
const db = new sqlite3.Database(DB_PATH);
db.serialize(() => {
    // use WAL for concurrent reads/writes
    db.exec("PRAGMA journal_mode = WAL;");
    // events table
    db.run(
        `CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL,
      source TEXT,
      severity TEXT,
      msg TEXT,
      meta TEXT,     -- JSON string
      raw TEXT       -- original JSON event as text
    )`
    );
    // blocks audit table
    db.run(
        `CREATE TABLE IF NOT EXISTS blocks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      who TEXT NOT NULL,
      when_ts INTEGER NOT NULL,
      reason TEXT,
      actor TEXT
    )`
    );
});

// --- helpers ---
function requireIngestAuth(req, res, next) {
    if (!INGEST_TOKEN) return next();
    const hdr = req.get("Authorization") || "";
    if (hdr === `Bearer ${INGEST_TOKEN}`) return next();
    return res.status(401).json({ error: "missing/invalid ingest token" });
}

function requireUIAuth(req, res, next) {
    if (!UI_TOKEN) return next();
    const hdr = req.get("Authorization") || "";
    if (hdr === `Bearer ${UI_TOKEN}`) return next();
    return res.status(401).json({ error: "missing/invalid UI token" });
}

// Insert a single event into DB (returns Promise of inserted rowid and row)
function insertEvent(evt) {
    return new Promise((resolve, reject) => {
        const ts = evt.ts || Math.floor(Date.now() / 1000);
        const source = evt.source || null;
        const severity = evt.severity || null;
        const msg = evt.msg || (typeof evt === "string" ? evt : JSON.stringify(evt));
        const meta = evt.meta ? JSON.stringify(evt.meta) : null;
        const raw = JSON.stringify(evt);
        const sql = `INSERT INTO events (ts, source, severity, msg, meta, raw) VALUES (?, ?, ?, ?, ?, ?)`;
        db.run(sql, [ts, source, severity, msg, meta, raw], function (err) {
            if (err) return reject(err);
            // fetch inserted row (we'll return it so we can broadcast)
            const rowid = this.lastID;
            db.get("SELECT id, ts, source, severity, msg, meta FROM events WHERE id = ?", [rowid], (e, row) => {
                if (e) return reject(e);
                // parse meta back to object
                if (row && row.meta) {
                    try { row.meta = JSON.parse(row.meta); } catch (err) { /* ignore */ }
                }
                resolve({ id: rowid, row });
            });
        });
    });
}

// Broadcast helper
function broadcastEvent(row) {
    io.emit("event", row);
}

// --- ROUTES ---

// ingest endpoint - batch or single
// expected body: { events: [ { ts, source, msg, meta, ... }, ... ] }
app.post("/ingest", requireIngestAuth, async (req, res) => {
    const payload = req.body;
    if (!payload || (!payload.events && !Array.isArray(payload.events))) {
        return res.status(400).json({ error: "payload must be { events: [...] }" });
    }
    const events = payload.events;
    if (!events.length) return res.status(200).json({ ok: true, inserted: 0 });

    // insert in a DB transaction and broadcast each inserted row
    db.serialize(async () => {
        db.run("BEGIN TRANSACTION");
        try {
            const results = [];
            for (const e of events) {
                // basic validation: require msg or raw text
                if (!e.msg && !e.raw && typeof e !== "string") continue;
                const { id, row } = await insertEvent(e);
                results.push(id);
                broadcastEvent(row);
            }
            db.run("COMMIT");
            return res.status(201).json({ ok: true, inserted: results.length, ids: results });
        } catch (err) {
            db.run("ROLLBACK");
            console.error("Ingest error:", err);
            return res.status(500).json({ error: "internal" });
        }
    });
});

// simple HTTP catch-up: GET /events?after_id=NN&limit=100
// GET /events?before_id=<id>&limit=<n>
// GET /events
// supports:
//  - GET /events?limit=100          -> returns newest `limit` events (id DESC)
//  - GET /events?before_id=123&limit=100 -> returns up to `limit` events where id < before_id (newest-first)
app.get("/events", (req, res) => {
    const beforeId = parseInt(req.query.before_id || "0", 10) || 0;
    const limit = Math.min(parseInt(req.query.limit || "100", 10), 2000);

    if (beforeId > 0) {
        db.all("SELECT id,ts,source,severity,msg,meta FROM events WHERE id < ? ORDER BY id DESC LIMIT ?", [beforeId, limit], (err, rows) => {
            if (err) return res.status(500).json({ error: "db" });
            for (const r of rows) {
                if (r.meta) {
                    try { r.meta = JSON.parse(r.meta); } catch (e) { }
                }
            }
            return res.json(rows);
        });
        return;
    }

    // default: newest events
    db.all("SELECT id,ts,source,severity,msg,meta FROM events ORDER BY id DESC LIMIT ?", [limit], (err, rows) => {
        if (err) return res.status(500).json({ error: "db" });
        for (const r of rows) {
            if (r.meta) {
                try { r.meta = JSON.parse(r.meta); } catch (e) { }
            }
        }
        return res.json(rows);
    });
});



// manual block endpoint
// { who: "1.2.3.4" | "AA:BB:..", reason: "too many fails", actor: "ui" }
app.post("/block", requireUIAuth, (req, res) => {
    const body = req.body || {};
    const who = body.who;
    if (!who) return res.status(400).json({ error: "who required" });
    const reason = body.reason || null;
    const actor = body.actor || "manual";

    // log to DB
    const when_ts = Math.floor(Date.now() / 1000);
    db.run("INSERT INTO blocks (who, when_ts, reason, actor) VALUES (?, ?, ?, ?)", [who, when_ts, reason, actor], function (err) {
        if (err) {
            console.error("block log error:", err);
            return res.status(500).json({ error: "db" });
        }

        // call local script to actually block (script must be secured!)
        // Example script signature: block_ip.sh <who>
        execFile(BLOCK_SCRIPT, [who], (execErr, stdout, stderr) => {
            if (execErr) {
                console.error("block exec error:", execErr, stderr);
                return res.status(500).json({ ok: false, error: "block_failed", detail: stderr || execErr.message });
            }
            // broadcast block as an "event" too
            const human = `BLOCKED ${who} reason=${reason || "manual"} actor=${actor}`;
            const evt = {
                ts: when_ts,
                source: "blocker",
                severity: "info",
                msg: human,
                meta: { who, reason, actor }
            };
            // insert into events table and broadcast (best-effort)
            insertEvent(evt).then(({ row }) => {
                broadcastEvent(row);
            }).catch(e => console.error("failed to insert block event:", e));

            return res.json({ ok: true, who, stdout: (stdout || "").slice(0, 1000) });
        });
    });
});

// Delete old logs endpoint
// POST /clear   body: { before_ts: 1699999999 }  OR  { before_id: 12345 }
app.post("/clear", requireUIAuth, (req, res) => {
    const body = req.body || {};
    const before_ts = body.before_ts ? parseInt(body.before_ts, 10) : null;
    const before_id = body.before_id ? parseInt(body.before_id, 10) : null;

    if (!before_ts && !before_id) {
        return res.status(400).json({ error: "provide before_ts or before_id" });
    }

    if (before_ts) {
        db.run("DELETE FROM events WHERE ts < ?", [before_ts], function (err) {
            if (err) {
                console.error("clear error:", err);
                return res.status(500).json({ error: "db" });
            }
            return res.json({ ok: true, deleted: this.changes || 0, method: "ts" });
        });
        return;
    }

    if (before_id) {
        db.run("DELETE FROM events WHERE id < ?", [before_id], function (err) {
            if (err) {
                console.error("clear error:", err);
                return res.status(500).json({ error: "db" });
            }
            return res.json({ ok: true, deleted: this.changes || 0, method: "id" });
        });
        return;
    }
});


// basic health
app.get("/health", (req, res) => res.json({ ok: true, now: Date.now(), db: DB_PATH }));

// --- WebSocket logic ---
io.on("connection", (socket) => {
    console.log("WS connected", socket.id);

    // we expect client to send their lastSeenId after connect:
    // socket.emit('hello', { lastSeenId: 123 })
    socket.on("hello", (payload) => {
        const last = payload && payload.lastSeenId ? parseInt(payload.lastSeenId, 10) : 0;
        if (last > 0) {
            // replay from DB (id > last)
            db.all("SELECT id, ts, source, severity, msg, meta FROM events WHERE id > ? ORDER BY id ASC LIMIT 2000", [last], (err, rows) => {
                if (err) {
                    socket.emit("error", { error: "replay_failed" });
                    return;
                }
                for (const r of rows) {
                    if (r.meta) {
                        try { r.meta = JSON.parse(r.meta); } catch (e) { }
                    }
                    socket.emit("event", r);
                }
                socket.emit("replay_done", { lastSeenId: rows.length ? rows[rows.length - 1].id : last });
            });
        } else {
            socket.emit("replay_done", { lastSeenId: last });
        }
    });

    socket.on("disconnect", () => {
        console.log("WS disconnected", socket.id);
    });
});

// --- start ---
server.listen(PORT, () => {
    console.log(`SOC backend listening on :${PORT}`);
});
