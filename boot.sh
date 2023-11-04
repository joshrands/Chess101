#!/bin/bash

dir=$(dirname $0)
cd $dir
./logger.sh
if [[ -n "$1" && "$1" == "tail" ]]; then
	echo "tailing error logs"
	tail -n0 -f logs/error.log &
fi
sudo python3 -u GameManager.py 2>> logs/error.log | tee logs/output.log
