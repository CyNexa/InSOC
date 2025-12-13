#!/bin/bash
echo "WARNING: DONT RUN THIS AGAIN IF SETUP IS DONE"

sleep 2
echo "Starting Agent Setup Process"
cd agent
sudo apt update
echo "-----------------------"
echo "Installing Python3 and Pip3"
sudo apt install -y python3
sudo apt install -y python3-pip
sudo apt install -y python3-venv
echo "Python3 and Pip3 Installed"

sleep 2
echo "Creating Virtual Environment"
python3 -m venv venv
echo "Virtual Environment Created"

sleep 2
echo "Installing Agent Dependencies"
pip3 install requests
echo "Agent Dependencies Installed"
cd ..

sleep 2
echo "Starting Backend Setup Process"

sleep 2
echo "Installing Node & NPM"
sudo apt install -y nodejs
echo "-----------------------"
sudo apt install -y npm
echo "Node & NPM Installed"

sleep 2
echo "Installing Backend Dependencies And Creating"
cd backend
npm install
cd ..

sleep 2
echo "Providing Execute Permissions to start.sh"
chmod 777 start.sh

sleep 2
echo "Setup Process Completed Successfully!"

exit