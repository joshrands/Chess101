from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Team:
    r: int
    g: int
    b: int
    name: str = "Wendy"

    def set_color(self) -> None:
        self.r = int(input("Enter red: "))
        self.g = int(input("Enter green: "))
        self.b = int(input("Enter blue: "))

    def set_name(self, name: str) -> None:
        self.name = name
