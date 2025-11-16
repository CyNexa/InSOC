⚠ NOTE: THIS IS STILL IN DEVELOPMENT PHASE & MAIN FEATURES WILL BE ADDED SOON.  
⚠ NOTE: RAN ON UBUNTU SERVER ONLY.

# InSOC System README

A simple lightweight SOC built using:

* Python log collector agent
* Express backend with SQLite databases
* WebSocket-powered realtime UI
* Tailwind-based dashboard

## Features

* Realtime log ingestion from multiple Linux log files
* Live UI stream with newest-at-top ordering
* Severity classification (info / warn / err) based on patterns
* Load older logs via timestamp paging
* Delete past logs from DB via UI button
* Auto-retention (logs auto-delete after 1 hour)
* Fully configurable ingest token + UI token

## Components

### 1. Collector Agent (Python)

Reads log files using `tail -F` logic, batches entries, and sends to backend via `/ingest`.
Handles spool directory for disconnected mode.

### 2. Express Backend

* Stores logs into `events.sqlite`
* Stores commands into `commands.sqlite`
* Broadcasts logs via WebSocket
* Provides `/events` (with before_ts paging)
* Provides `/clear` for deletion
* Provides `/cmd` + `/cmds`
* Static host for UI at `/`

### 3. Web UI

* Shows newest logs first
* Older logs load on scroll / button
* Tailwind cards with severity coloring
* IST timestamp formatting
* Filtering, search, pause mode
* Delete-past button

## Directory Structure

```
InSOC/
  backend/
    node_modules
    public/
      ui.html
    init_db.js
    server.js
    package.json
    package-lock.json
    
  agent/
    agent.py
  
  setup.sh -- ⚠ Only Run Once For Setup
  start.sh -- Use To Start The SOC

  readme.md
```

## Environment Variables (NOT SET IN THIS EDITION)

```
INGEST_TOKEN= (optional)
UI_TOKEN= (optional)
BACKEND_URL=http://127.0.0.1:5000
```

## Setup Process

```
cd logmonitor
chmod 777 setup.sh
./setup.sh
```

## Starting InSOC

```
cd logmonitor
./start.sh
```

## Security Notes

* Command logging may reveal sensitive data; configure filters properly.
* Use UI_TOKEN for protected endpoints.
* Restrict backend binding to local network if exposed.


This SOC is designed to stay small, fast. (Internet Needed For TailwindCSS [Will Fix In Future Update])


## ⚠️ SAFETY GUARANTEE

THIS SOC SYSTEM IS BUILT FOR PERSONAL, LOCAL, AND EDUCATIONAL USE ONLY.  
ALL LOGS STAY ON YOUR MACHINE UNLESS YOU EXPLICITLY CONFIGURE OTHERWISE.  
THE SYSTEM ONLY COLLECTS DATA FROM LOG FILES YOU MANUALLY SPECIFY AND CONTAINS NO HIDDEN DATA CAPTURE, NO EXTERNAL UPLOADS, AND NO SURVEILLANCE FEATURES.  
COMMAND LOGGING IS OPTIONAL AND DISABLED BY DEFAULT, AS IT MAY CONTAIN SENSITIVE INFORMATION.  
THIS TOOL IS NOT INTENDED TO MONITOR OTHER USERS WITHOUT CONSENT AND EXISTS SOLELY TO HELP YOU AUDIT, SECURE, AND UNDERSTAND **YOUR OWN SYSTEMS** IN A SAFE AND TRANSPARENT WAY.  
