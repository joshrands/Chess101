import pygame
pygame.init()

def playSound(filename):
    sound = pygame.mixer.Sound(filename)
    sound.play()

playSound("test.wav")
