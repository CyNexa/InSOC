const express = require("express");
const session = require("express-session");
const path = require("path");
const http = require("http");
const socketio = require("socket.io");
require("dotenv").config();

const { ensureAuth } = require("./authMiddleware");

const app = express();
const server = http.createServer(app);
const io = socketio(server, {
  cors: {
    origin: "*",
  },
});

app.set("io", io);

// view engine
app.set("view engine", "ejs");
app.set("views", path.join(__dirname, "..", "views"));

// static + parsers
app.use(express.static(path.join(__dirname, "..", "public")));
app.use(express.urlencoded({ extended: true }));
app.use(express.json());

// sessions
app.use(
  session({
    secret: process.env.SESSION_SECRET || "changeme",
    resave: false,
    saveUninitialized: false,
  })
);

// routes
const authRoutes = require("./routes/auth");
const logsRoutes = require("./routes/logs");
const blocksRoutes = require("./routes/blocks");
const commandsRoutes = require("./routes/commands");
const apiLogsRoutes = require("./routes/api_logs");

app.use("/", authRoutes);
app.use("/", apiLogsRoutes);
app.use("/", ensureAuth, logsRoutes);
app.use("/", ensureAuth, blocksRoutes);
app.use("/", ensureAuth, commandsRoutes);

// default redirect
app.get("/", (req, res) => {
  if (req.session.user) return res.redirect("/dashboard");
  return res.redirect("/login");
});

// Socket.io
io.on("connection", (socket) => {
  console.log("Web client connected to socket.io");
  socket.on("disconnect", () => {
    console.log("Web client disconnected");
  });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log(`SOC backend listening on port ${PORT}`);
});
