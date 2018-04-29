# Master Class - Controls the arduinos and receives data
# Useful methods:
# readData - reads data from Arduinos and updates gridStates (0 activated 1 not)
# getCellState - get the state of a specific cell args: row, col

import smbus
import time

class Master:
   
    bus = smbus.SMBus(1)

    # Define arduino addresses
    # MUST MATCH ON ARDUINO SIDE
    rowA = 0x04
    rowB = 0x05
    rowC = 0x06
    rowD = 0x07
    rowE = 0x08
    rowF = 0x09
    rowG = 0x0a
    rowH = 0x0b

    gridStates = [1] * 8

    def __init__(self):
        # populate states
        for i in range(8):
            self.gridStates[i] = [1] * 8
   
        self.initialize()
    
    def initialize(self):
        # loop through and compare every cell to gridStates
        self.fillRowData(self.rowA, 0)
        self.fillRowData(self.rowB, 1)
        self.fillRowData(self.rowC, 2)
        self.fillRowData(self.rowD, 3)
        self.fillRowData(self.rowE, 4)
        self.fillRowData(self.rowF, 5)
        self.fillRowData(self.rowG, 6)
        self.fillRowData(self.rowH, 7)

        self.printBoardStates()

    def fillRowData(self, row, rowNum):
        self.writeToRow(row, 42)
        time.sleep(0.05)
        val = self.readFromRow(row)
        self.updateRowStates(rowNum, val)

    def getCellState(self, row, col):
        return self.gridStates[row][col]

    def printBoardStates(self):
        for r in range(8):
            print(self.gridStates[r])

    def updateRowStates(self, row, colStates):
        change = False
        for i in range(7, -1, -1):
#            print(colStates)
            if (colStates - 2**i >= 0):
                colStates = colStates - 2**i
                # check if change
                if (self.gridStates[row][i] != 1):
                    self.gridStates[row][i] = 1
                    change = True 
            else:
                if (self.gridStates[row][i] != 0):
                    self.gridStates[row][i] = 0
                    change = True 
        if (change == True):
            print("Board Changed: ")
            self.printBoardStates()

    # get all occupied cells
    def readData(self):
        self.fillRowData(self.rowA, 0)        
        self.fillRowData(self.rowB, 1)
        self.fillRowData(self.rowC, 2)
        self.fillRowData(self.rowD, 3)
        self.fillRowData(self.rowE, 4)
        self.fillRowData(self.rowF, 5)
        self.fillRowData(self.rowG, 6)
        self.fillRowData(self.rowH, 7)
       #print("Send data")

    def writeToRow(self, address, value):
        # handle i/o error
        handled = False
        while not handled:
            try:
                self.bus.write_byte(address, value)
                handled = True
            except IOError:
                handled = False
                print("I/O error... handling...")
                time.sleep(0.5)
                
        return -1

    def readFromRow(self, address):
        number = self.bus.read_byte(address)
        return number

# Test master class
#master = Master()

#while True:
    # loop through and detect changes
#    master.readData()
#    time.sleep(0.5)
