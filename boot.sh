#!/bin/bash

dir=$(dirname $0)
cd $dir
git pull
./logger.sh
sudo python3 -u GameManager.py 2>> logs/error.log | tee logs/output.log

