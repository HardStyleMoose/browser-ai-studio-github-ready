import random

class SharedReplayBuffer:

    def __init__(self, size=50000):
        self.buffer = []

    def add(self, exp):
        self.buffer.append(exp)

        if len(self.buffer) > 50000:
            self.buffer.pop(0)

    def sample(self, batch):
        return random.sample(self.buffer, batch)