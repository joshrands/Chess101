from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Team:
    """Identifies a chess side by RGB color and an optional display name.

    Team equality throughout the codebase is determined solely by the ``r``
    channel (this is an intentional preserved behaviour).

    Attributes:
        r: Red component of the team's LED color (0–255).
        g: Green component of the team's LED color (0–255).
        b: Blue component of the team's LED color (0–255).
        name: Human-readable label for the team; defaults to ``"Wendy"``.
    """

    r: int
    g: int
    b: int
    name: str = "Wendy"

    def set_color(self) -> None:
        """Prompt the user to enter new RGB values and update the team's color."""
        self.r = int(input("Enter red: "))
        self.g = int(input("Enter green: "))
        self.b = int(input("Enter blue: "))

    def set_name(self, name: str) -> None:
        """Set the team's display name.

        Args:
            name: The new name to assign to this team.
        """
        self.name = name
