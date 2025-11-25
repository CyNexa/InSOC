⚠ NOTE: THIS IS STILL IN DEVELOPMENT PHASE & MAIN FEATURES WILL BE ADDED SOON.  
⚠ NOTE: RUN ON UBUNTU SERVER ONLY.

# InSOC System README

A simple lightweight SOC built using:

* Python log collector agent
* Express(EJS) backend with SQLite databases
* WebSocket-powered realtime UI
* Tailwind-based dashboard

## Features

* Realtime log ingestion from multiple Linux log files
* Live UI stream with newest-at-top ordering
* Severity classification (Info / Warn / High) etc. based on patterns
* Load older logs via timestamp paging
* Delete past logs from DB via UI button
* Auto-retention (logs auto-delete after 1 hour)
* Fully configurable ingest token + UI token

## Components

### 1. Collector Agent (Python)

Reads log files in /var/log that contains `.log` at end, batches entries, and saves to SQLite DB.
Handles spool directory for disconnected mode.

### 2. Express Backend

Fetches logs from DB and sends over the websocket to web UI
#### Pages
* /login
* /dashboard
* /server/logs
* /server/blocks
* /server/commands
* /client/logs
* /client/blocks
* /client/commands

### 3. Web UI

* Shows newest logs first
* Older logs load on scroll
* Tailwind cards with severity coloring
* IST timestamp formatting
* Filtering, search.

## Directory Structure

```
InSOC/
├── backend/
│    ├── data/
│    ├── node_modules/
│    ├── public/
│    │    ├── css/
│    │    │    ├── extra.css
│    │    │    └── styles.css
│    │    ├── js/
│    │    │    ├── blocks.js
│    │    │    ├── commands.js
│    │    │    ├── dashboard.js
│    │    │    └── logs.js
│    │    └── favicon.png
│    ├── src/
│    │    ├── server.js
│    │    ├── db.js
│    │    ├── authMiddleware.js
│    │    ├── input.css (configurational)
│    │    └── routes/
│    │         ├── api_logs.js
│    │         ├── auth.js
│    │         ├── blocks.js
│    │         ├── commands.js
│    │         └── logs.js
│    ├── views/
│    │    ├── layout.ejs
│    │    ├── login.ejs
│    │    ├── dashboard.ejs
│    │    ├── client_logs.ejs
│    │    ├── client_blocks.ejs
│    │    ├── client_commands.ejs
│    │    ├── server_logs.ejs
│    │    ├── server_blocks.ejs
│    │    └── server_commands.ejs
│    ├── .env
│    ├── package.json
│    ├── package-lock.json
│
├── agent/
│    ├── client_config/
│    │    ├── client_agent.py
│    │    ├── client_config.py         // Main Client Config
│    │    ├── insoc-client.json
│    │    └── severity_rules.json
│    ├── server_agent.py
│    ├── firewall_agent.py             // Work in progress
│    ├── config.json                   // Main Server Config
│    ├── severity_rules.json
│ 
├── setup.sh -- ⚠ Only Run Once For Setup
├── start.sh -- Use To Start The SOC
│
└── readme.md
```

## Environment Variables 

### .env
```
// /backend/.env
SESSION_SECRET=
ADMIN_USERNAME=
ADMIN_PASSWORD=
DB_PATH=./data/soc.db
PORT=3000
AGENT_API_KEY=abc123

```

## Server Setup
### Automatic
```
cd InSOC
chmod 777 setup.sh
./setup.sh
```

### Manual
```
sudo apt update
sudo apt install -y python3
sudo apt install -y python3-pip
sudo apt install -y python3-venv
sudo apt install -y nodejs
sudo apt install -y npm
```
```
cd agent
python3 -m venv venv
pip3 install requests -y
```
```
cd backend
npm install
```

## Client Setup
1. Move `clinet_agent.py`, `client_config.json`, `severity_rules.json` to `/opt/insoc-client/`
2. Move `insoc-client.service` to `/etc/systemd/system/`

```
// Note: This is automation of upper text instructioned work.

cd client_config

sudo mv clinet_agent.py /opt/insoc-client/
sudo mv client_config.json /opt/insoc-client/
sudo mv severity_rules.json /opt/insoc-client/

sudo mv insoc-client.service /etc/systemd/system/
```
```
sudo systemctl reload-daemon
sudo systemctl enable insoc-client.service
```

## Starting InSOC
### Server
```
cd InSOC
./start.sh
```
### Client
```
sudo systemctl start insoc-client.service
sudo systemctl status insoc-client.service

// The "Client Log Agent(service)" once started it runs all time and auto starts at restart
```

## Security Notes

* Command logging may reveal sensitive data; configure filters properly.
* Use `AGENT_API_KEY=` for protected endpoints.
* Restrict backend binding to local network if exposed.


This SOC is designed to stay small, fast. (Internet Needed For TailwindCSS [Will Fix In Future Update])


## ⚠️ SAFETY GUARANTEE

THIS SOC SYSTEM IS BUILT FOR PERSONAL, LOCAL, AND EDUCATIONAL USE ONLY.  
ALL LOGS STAY ON YOUR MACHINE UNLESS YOU EXPLICITLY CONFIGURE OTHERWISE.  
THE SYSTEM ONLY COLLECTS DATA FROM LOG FILES YOU MANUALLY SPECIFY AND CONTAINS NO HIDDEN DATA CAPTURE, NO EXTERNAL UPLOADS, AND NO SURVEILLANCE FEATURES.  
COMMAND LOGGING IS OPTIONAL AND DISABLED BY DEFAULT, AS IT MAY CONTAIN SENSITIVE INFORMATION.  
THIS TOOL IS NOT INTENDED TO MONITOR OTHER USERS WITHOUT CONSENT AND EXISTS SOLELY TO HELP YOU AUDIT, SECURE, AND UNDERSTAND **YOUR OWN SYSTEMS** IN A SAFE AND TRANSPARENT WAY.