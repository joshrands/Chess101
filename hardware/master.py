from __future__ import annotations

import logging
import smbus
import time

from hardware.sensor import BoardSensor

logger = logging.getLogger(__name__)


class Master(BoardSensor):

    ROW_ADDRESSES = [0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b]
    WRITE_TRIGGER = 42

    def __init__(self) -> None:
        self.bus = smbus.SMBus(1)
        self.grid_states: list[list[int]] = [[0] * 8 for _ in range(8)]
        self.initialize()

    def initialize(self) -> None:
        for i, addr in enumerate(self.ROW_ADDRESSES):
            self.fill_row_data(addr, i)
        self.print_board_states()

    def fill_row_data(self, row: int, row_num: int) -> None:
        self.write_to_row(row, self.WRITE_TRIGGER)
        time.sleep(0.01)
        val = self.read_from_row(row)
        self.update_row_states(row_num, val)

    def get_cell_state(self, row: int, col: int) -> int:
        return self.grid_states[row][col]

    def print_board_states(self) -> None:
        for r in range(8):
            logger.debug("%s", self.grid_states[r])

    def update_row_states(self, row: int, col_states: int) -> None:
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
            logger.info("Board Changed: ")
            self.print_board_states()

    def read_data(self) -> None:
        for i, addr in enumerate(self.ROW_ADDRESSES):
            self.fill_row_data(addr, i)

    def write_to_row(self, address: int, value: int) -> int:
        handled = False
        while not handled:
            try:
                self.bus.write_byte(address, value)
                handled = True
            except IOError:
                handled = False
                logger.warning("I/O error... handling...")
                time.sleep(0.5)
        return -1

    def read_from_row(self, address: int) -> int:
        handled = False
        while not handled:
            try:
                number = self.bus.read_byte(address)
                handled = True
            except IOError:
                handled = False
                logger.warning("I/O error... handling...")
                time.sleep(0.5)
        return number
