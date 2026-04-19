#!/bin/bash

dir=$(dirname $0)
cd $dir
./logger.sh
sudo .venv/bin/python3.9 -u GameManager.py 2>> logs/error.log | tee logs/output.log

