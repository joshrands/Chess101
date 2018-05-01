import pygame
pygame.mixer.pre_init(44100, 16, 2, 4096) #frequency, size, channels, buffersize pygame.mixer.pre_init(44100, 16, 2, 4096) #frequency, size, channels, buffersize
pygame.init()

def playSound(filename):
    sound = pygame.mixer.Sound(filename)
    sound.play()

playSound('./test.wav')
