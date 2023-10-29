#!/bin/bash

LOG_DIR="/home/pi/Documents/Chess101/logs"

mv -f $LOG_DIR/output.log.2 $LOG_DIR/output.log.3
mv -f $LOG_DIR/output.log.1 $LOG_DIR/output.log.2
mv -f $LOG_DIR/output.log $LOG_DIR/output.log.1
touch $LOG_DIR/output.log
chown pi:pi $LOG_DIR/output.log

echo "finished moving logs"
