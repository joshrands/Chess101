#!/bin/bash

mv -f /home/pi/Documents/Chess101/output.log.2 /home/pi/Documents/Chess101/output.log.3
mv -f /home/pi/Documents/Chess101/output.log.1 /home/pi/Documents/Chess101/output.log.2
mv -f /home/pi/Documents/Chess101/output.log /home/pi/Documents/Chess101/output.log.1

echo "finished moving logs"
