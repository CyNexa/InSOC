#!/bin/bash
trap "echo 'Shutting All Services'; kill 0" SIGINT

echo "Starting Node Server..."
cd backend
node src/server.js &
cd ..

echo "Starting Python Agents..."
cd agent
python3 server_agent.py &
python3 firewall_agent.py &
cd ..

echo "All services launched! Ctrl+C to stop everything."

wait