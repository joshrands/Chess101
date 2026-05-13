#!/bin/bash

dir=$(dirname $0)
cd $dir

# If wlan0 has no IP, WiFi didn't connect — start captive portal in background.
# Must run BEFORE git stash (which would revert uncommitted changes to this file).
# Once this change is committed, git stash is a no-op and this is safe.
if ! ip addr show wlan0 2>/dev/null | grep -q "inet "; then
    echo "No WiFi connection — starting captive portal (Chess101-Setup)"
    sudo .venv/bin/python3.9 -u wifi_setup.py >> logs/wifi_setup.log 2>&1 &
fi

git stash
git pull
./boot.sh
