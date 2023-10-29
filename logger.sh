#!/bin/bash

mv -f /home/pi/Documents/Chess101/output.log.2 /home/pi/Documents/Chess101/output.log.3
mv -f /home/pi/Documents/Chess101/output.log.1 /home/pi/Documents/Chess101/output.log.2
mv -f /home/pi/Documents/Chess101/output.log /home/pi/Documents/Chess101/output.log.1
touch /home/pi/Documents/Chess101/output.log
chown pi:pi /home/pi/Documents/Chess101/output.log

echo "finished moving logs"
