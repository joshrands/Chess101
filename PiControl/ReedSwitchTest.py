# Author: Josh Rands
# Date: 4/3/2018
# Description: Test reed switch tolerance

# import libraries
import RPi.GPIO as GPIO
import numpy as np
import time

# setup variables for PINs
BLUE_LED = 20
YELLOW_LED = 19

BLUE_REED = 21
YELLOW_REED = 22

# set mode of GPIO
GPIO.setmode(GPIO.BCM)

# setup GPIO ports
GPIO.setup(BLUE_LED, GPIO.OUT)
GPIO.setup(YELLOW_LED, GPIO.OUT)

GPIO.setup(BLUE_REED, GPIO.IN, GPIO.PUD_DOWN)
GPIO.setup(YELLOW_REED, GPIO.IN, GPIO.PUD_DOWN) # consider switching to PUD_UP

try:
    while True:
        # capture and print the input from the reed switch
        yellow = GPIO.input(YELLOW_REED)
        blue = GPIO.input(BLUE_REED)
        
        if (blue == True and yellow == False):
            GPIO.output(BLUE_LED, True)
        else:
            GPIO.output(BLUE_LED, False)
        if (yellow == True and blue == False):
            GPIO.output(YELLOW_LED, True)
        else:
            GPIO.output(YELLOW_LED, False)
    time.sleep(.00000001)
    
except(KeyboardInterrupt, SystemExit):
    print("Excepted interrupt")
    GPIO.output(BLUE_LED, False)
    GPIO.output(YELLOW_LED, False)
    exit
finally:
    GPIO.cleanup()

