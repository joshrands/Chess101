#!/bin/bash
sudo cp /etc/apt/sources.list.bak /etc/apt/sources.list
sudo apt-get update
echo "Sources restored. Current python3 version:"
python3 --version
