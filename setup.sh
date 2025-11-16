#!/bin/bash
echo "Starting the Setup Process..."

cd backend
npm install
cd ..

node backend/init_db.js

chmod 777 start.sh

echo "WARNING: DONT RUN THIS AGAIN IF SETUP IS DONE"

exit