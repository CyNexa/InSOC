#!/bin/bash
echo "🔥 Starting Python Agent..."
sudo python3 agent/agent.py &
PID1=$!

echo "⚡ Starting Node Server..."
cd backend
sudo node server.js &
PID2=$!

echo "🚀 Both services launched!"
echo "Python Agent PID: $PID1"
echo "Node Server PID: $PID2"

wait