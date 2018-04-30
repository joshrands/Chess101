import pygame
pygame.init()

def playSound(filename):
    pygame.mixer.music.load(filename)
    pygame.mixer.music.play()

playSound("test.wav")
