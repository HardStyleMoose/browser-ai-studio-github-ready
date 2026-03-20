class ActionExecutor:

    def __init__(self, input_manager):

        self.input = input_manager

    def execute(self, action):

        actions = {

            0: lambda: self.input.press_key("w"),
            1: lambda: self.input.press_key("a"),
            2: lambda: self.input.press_key("s"),
            3: lambda: self.input.press_key("d"),
            4: lambda: self.input.click_random(),
            5: lambda: self.input.press_key("space")
        }

        if action in actions:
            actions[action]()