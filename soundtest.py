import pygame
pygame.init()

def playSound(filename):
    pygame.mixer.Sound(filename)
    pygame.mixer.play()

playSound("test.wav")
