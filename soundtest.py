import pygame
import os
import time

print(os.getcwd())
pygame.mixer.pre_init(44100, 16, 2, 4096) #frequency, size, channels, buffersize pygame.mixer.pre_init(44100, 16, 2, 4096) #frequency, size, channels, buffersize
pygame.init()
sound = pygame.mixer.Sound('/home/pi/Documents/Chess101/beautiful_friendship.wav')
sound.play()
time.sleep(2)
sound.stop()
