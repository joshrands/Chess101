#!/bin/bash

mv /home/rpi/Documents/Chess101/output.log.2 home/rpi/Documents/Chess101/output.log.3
mv /home/rpi/Documents/Chess101/output.log.1 home/rpi/Documents/Chess101/output.log.2
mv /home/rpi/Documents/Chess101/output.log home/rpi/Documents/Chess101/output.log.1

echo "finished moving logs"
