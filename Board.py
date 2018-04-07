#!/usr/bin/env python
from samplebase import SampleBase

class Board(SampleBase):
    def __init__(self, *args, **kwargs):
        super(Board, self).__init__(*args, **kwargs)
    
    def lightCell(self, canvas, x, y, r, g, b):
        #offset_canvas = self.matrix.CreateFrameCanvas()
        for i in range(0, 4):
            for j in range(0, 4):
                canvas.SetPixel(x*4 + i, y*4 + j, r, g, b)


    def run(self):
        print("Running lights")
        while True:
            offset_canvas = self.matrix.CreateFrameCanvas()
            
            self.lightCell(offset_canvas, 4, 3, 64, 180, 232)

            offset_canvas = self.matrix.SwapOnVSync(offset_canvas)

# Main function
#if __name__ == "__main__":
#    simple_square = Board()
#    if (not simple_square.process()):
#        simple_square.print_help()
