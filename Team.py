# Team class - holds all 16 pieces


class Team:
    # holds pieces
    def __init__(self, r, g, b):
        self.r = r
        self.g = g
        self.b = b
        self.name = "Wendy"

    def setColor(self):
        self.r = int(input("Enter red: "))
        self.g = int(input("Enter green: "))
        self.b = int(input("Enter blue: "))

    def setName(self, name):
        self.name = name

#team = Team(0, 0, 0)
# team.setColor()
