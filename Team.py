class Team:
    def __init__(self, r, g, b):
        self.r = r
        self.g = g
        self.b = b
        self.name = "Wendy"

    def set_color(self):
        self.r = int(input("Enter red: "))
        self.g = int(input("Enter green: "))
        self.b = int(input("Enter blue: "))

    def set_name(self, name):
        self.name = name
