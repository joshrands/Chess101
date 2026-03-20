import smbus
import time


class Master:

    bus = smbus.SMBus(1)

    rowA = 0x04
    rowB = 0x05
    rowC = 0x06
    rowD = 0x07
    rowE = 0x08
    rowF = 0x09
    rowG = 0x0a
    rowH = 0x0b

    grid_states = [1] * 8

    def __init__(self):
        for i in range(8):
            self.grid_states[i] = [1] * 8
        self.initialize()

    def initialize(self):
        self.fill_row_data(self.rowA, 0)
        self.fill_row_data(self.rowB, 1)
        self.fill_row_data(self.rowC, 2)
        self.fill_row_data(self.rowD, 3)
        self.fill_row_data(self.rowE, 4)
        self.fill_row_data(self.rowF, 5)
        self.fill_row_data(self.rowG, 6)
        self.fill_row_data(self.rowH, 7)
        self.print_board_states()

    def fill_row_data(self, row, row_num):
        self.write_to_row(row, 42)
        time.sleep(0.01)
        val = self.read_from_row(row)
        self.update_row_states(row_num, val)

    def get_cell_state(self, row, col):
        return self.grid_states[row][col]

    def print_board_states(self):
        for r in range(8):
            print(self.grid_states[r])

    def update_row_states(self, row, col_states):
        change = False
        for i in range(7, -1, -1):
            if col_states - 2**i >= 0:
                col_states = col_states - 2**i
                if self.grid_states[row][i] != 1:
                    self.grid_states[row][i] = 1
                    change = True
            else:
                if self.grid_states[row][i] != 0:
                    self.grid_states[row][i] = 0
                    change = True
        if change:
            print("Board Changed: ")
            self.print_board_states()

    def read_data(self):
        self.fill_row_data(self.rowA, 0)
        self.fill_row_data(self.rowB, 1)
        self.fill_row_data(self.rowC, 2)
        self.fill_row_data(self.rowD, 3)
        self.fill_row_data(self.rowE, 4)
        self.fill_row_data(self.rowF, 5)
        self.fill_row_data(self.rowG, 6)
        self.fill_row_data(self.rowH, 7)

    def write_to_row(self, address, value):
        handled = False
        while not handled:
            try:
                self.bus.write_byte(address, value)
                handled = True
            except IOError:
                handled = False
                time.sleep(0.5)
        return -1

    def read_from_row(self, address):
        handled = False
        while not handled:
            try:
                number = self.bus.read_byte(address)
                handled = True
            except IOError:
                handled = False
                time.sleep(0.5)
        return number
