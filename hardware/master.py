from __future__ import annotations

import logging
import smbus
import time

from hardware.sensor import BoardSensor
from hardware.rotation import rotate_cell

logger = logging.getLogger(__name__)


class Master(BoardSensor):
    """I2C master that polls eight Arduino row controllers for piece positions.

    Each Arduino sits at a fixed I2C address (0x04–0x0b) and responds with a
    single byte whose bits represent the eight reed-switch states for that row.
    A set bit (1) means the cell is empty; a clear bit (0) means a piece is
    present.
    """

    ROW_ADDRESSES = [0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b]
    WRITE_TRIGGER = 42

    def __init__(self, rotation: int = 0) -> None:
        """Open I2C bus 1, zero-initialise the grid cache, and poll all rows.

        Args:
            rotation: Board rotation in degrees CW (0, 90, 180, or 270).
        """
        self._rotation = rotation
        self.bus = smbus.SMBus(1)
        self.grid_states: list[list[int]] = [[0] * 8 for _ in range(8)]
        self.initialize()

    def initialize(self) -> None:
        """Perform the initial poll of every row and log the starting board state."""
        for i, addr in enumerate(self.ROW_ADDRESSES):
            self.fill_row_data(addr, i)
        self.print_board_states()

    def fill_row_data(self, row: int, row_num: int) -> None:
        """Trigger an Arduino, wait for it to sample, then read and store its byte.

        Args:
            row: I2C address of the Arduino to query.
            row_num: Zero-based row index used to update ``grid_states``.
        """
        self.write_to_row(row, self.WRITE_TRIGGER)
        time.sleep(0.01)
        val = self.read_from_row(row)
        self.update_row_states(row_num, val)

    def get_cell_state(self, row: int, col: int) -> int:
        """Return the cached sensor value for a single cell.

        Applies board rotation then transposes the lookup (col, row) to align
        physical reed switch layout with the corrected visual rendering.

        Args:
            row: Zero-based board row (0 = teamR back rank).
            col: Zero-based board column.

        Returns:
            0 if a piece is present, 1 if the cell is empty.
        """
        rr, rc = rotate_cell(row, col, self._rotation)
        return self.grid_states[rc][rr]

    def print_board_states(self) -> None:
        """Log the full 8x8 grid cache at DEBUG level."""
        for r in range(8):
            logger.debug("%s", self.grid_states[r])

    def update_row_states(self, row: int, col_states: int) -> None:
        """Decode a raw sensor byte into per-column states and cache them.

        The byte is treated as a bitmask: bit 7 corresponds to column 7, bit 0
        to column 0.  If any cell value changed the updated board is logged at
        INFO level.

        Args:
            row: Zero-based row index to update in ``grid_states``.
            col_states: Raw byte received from the Arduino for this row.
        """
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
        """Poll all eight Arduinos and refresh the internal grid cache."""
        for i, addr in enumerate(self.ROW_ADDRESSES):
            self.fill_row_data(addr, i)

    def write_to_row(self, address: int, value: int) -> int:
        """Send a single byte to an Arduino, retrying indefinitely on I2C errors.

        Args:
            address: I2C address of the target Arduino.
            value: Byte value to write (typically ``WRITE_TRIGGER``).

        Returns:
            -1 always (return value is unused by callers).
        """
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
        """Read a single byte from an Arduino, retrying indefinitely on I2C errors.

        Args:
            address: I2C address of the target Arduino.

        Returns:
            The byte value returned by the Arduino.
        """
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
