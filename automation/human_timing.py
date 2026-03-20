import random
import time

import pyautogui


class HumanTiming:

    def reaction_delay(self):
        return random.uniform(0.15, 0.65)

    def key_hold_time(self):
        return random.uniform(0.05, 0.25)

    def pause_between_actions(self):
        return random.uniform(0.2, 1.2)

    def apply_delay(self):
        time.sleep(self.reaction_delay())


# ...existing code...


class BehaviorRandomizer:

    def random_offset(self, x, y):
        return x + random.randint(-3, 3), y + random.randint(-3, 3)


class SpeedController:

    def __init__(self):
        self.speed_factor = 1.0

    def adjust(self, reward):
        if reward > 5:
            self.speed_factor *= 0.95
