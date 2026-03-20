import numpy as np

class RewardDiscovery:

    def __init__(self):

        self.previous_state = None

    def calculate_reward(self, current_state, action):

        if self.previous_state is None:

            self.previous_state = current_state

            return 0

        reward = 0

        reward += (current_state[0] - self.previous_state[0]) * 10  # health

        reward += (current_state[1] - self.previous_state[1]) * -5  # enemy count

        reward += (current_state[2] - self.previous_state[2]) * 1   # gold

        reward += (current_state[3] - self.previous_state[3]) * 2   # damage

        self.previous_state = current_state

        return reward