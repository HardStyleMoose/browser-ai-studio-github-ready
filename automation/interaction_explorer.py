import random

class InteractionExplorer:

    def __init__(self, input_manager):
        self.input = input_manager

    def random_action(self):

        actions = [
            lambda: self.input.click_random(),
            lambda: self.input.press_key("w"),
            lambda: self.input.press_key("a"),
            lambda: self.input.press_key("s"),
            lambda: self.input.press_key("d")
        ]

        action = random.choice(actions)
        action()