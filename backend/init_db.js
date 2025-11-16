// init_db.js
// Usage: node init_db.js [./events.sqlite]
// Defaults to ./events.sqlite if no arg supplied.

const sqlite3 = require('sqlite3').verbose();
const path = process.argv[2] || './events.sqlite';

console.log('Initializing SQLite DB at:', path);

const db = new sqlite3.Database(path, (err) => {
  if (err) {
    console.error('Failed to open DB:', err);
    process.exit(1);
  }
});

// Wrap in serialize to run sequentially
db.serialize(() => {
  try {
    console.log('Setting PRAGMAs...');
    db.run("PRAGMA journal_mode = WAL;");
    db.run("PRAGMA synchronous = NORMAL;");
    db.run("PRAGMA temp_store = MEMORY;");

    console.log('Creating tables if they do not exist...');
    db.run(`CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL,
      source TEXT,
      severity TEXT,
      msg TEXT,
      meta TEXT,
      raw TEXT
    );`);

    db.run(`CREATE TABLE IF NOT EXISTS blocks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      who TEXT NOT NULL,
      when_ts INTEGER NOT NULL,
      reason TEXT,
      actor TEXT
    );`);

    console.log('All done. DB initialized.');
  } catch (e) {
    console.error('Initialization error:', e);
  }
});

// Close DB cleanly
db.close((err) => {
  if (err) {
    console.error('Error closing DB:', err);
    process.exit(1);
  }
  process.exit(0);
});
