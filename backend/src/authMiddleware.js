require("dotenv").config();

function ensureAuth(req, res, next) {
  if (req.session && req.session.user) return next();
  return res.redirect("/login");
}

function verifyApiKey(req, res, next) {
  const key = req.headers["x-api-key"];
  if (!key || key !== process.env.AGENT_API_KEY) {
    return res.status(401).json({ error: "Unauthorized" });
  }
  return next();
}

module.exports = { ensureAuth, verifyApiKey };
