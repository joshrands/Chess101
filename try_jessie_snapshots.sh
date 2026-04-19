#!/bin/bash
# Try different snapshot dates for Raspbian Jessie to find one with the packages

DATES=("20170701" "20160501" "20160101" "20151101" "20150501")

for date in "${DATES[@]}"; do
  echo "=== Trying snapshot date: $date ==="
  sudo tee /etc/apt/sources.list > /dev/null << EOF
deb http://snapshot.debian.org/archive/debian/${date}/ jessie main contrib non-free
deb http://snapshot.debian.org/archive/raspbian/${date}/ jessie main contrib non-free rpi
deb http://archive.raspberrypi.org/debian/ jessie main ui
EOF
  sudo apt-get update -o Acquire::Check-Valid-Until=false -q 2>&1 | cat
  if [ $? -eq 0 ]; then
    echo "SUCCESS with date $date"
    break
  else
    echo "Failed with date $date, trying next..."
  fi
done

echo "If one succeeded, now run the install command again."
