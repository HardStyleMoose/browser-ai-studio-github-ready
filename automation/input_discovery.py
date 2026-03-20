import random
import numpy as np

COMMON_KEYS = [
    "w", "a", "s", "d",
    "space", "shift", "ctrl",
    "up", "down", "left", "right",
    "enter", "esc"
]

class InputDiscovery:

    def __init__(self, keyboard_keys):

        self.keys = keyboard_keys

    def random_action(self):

        action_type = random.choice(["mouse","key"])

        if action_type == "key":

            key = random.choice(self.keys)

            return ("key",key)

        else:

            x = random.randint(0,1920)
            y = random.randint(0,1080)

            return ("mouse",x,y)

    def screen_difference(self,frame1,frame2):

        return float(np.mean(np.abs(frame1-frame2)))


class InputEffectAnalyzer:

    def __init__(self, threshold=5):

        self.threshold = threshold

    def has_effect(self, diff):

        return diff > self.threshold


class ActionLibrary:

    def __init__(self):

        self.actions = []

    def add(self, action):

        if action not in self.actions:

            self.actions.append(action)

    def sample(self):

        import random

        return random.choice(self.actions)