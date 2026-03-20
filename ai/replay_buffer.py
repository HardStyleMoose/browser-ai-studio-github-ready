"""Replay buffer for experience replay."""

import random
from typing import Any, List


class ReplayBuffer:
    def __init__(self, size: int = 10000):
        self.buffer: List[Any] = []
        self.max_size = size

    def add(self, experience: Any) -> None:
        if len(self.buffer) >= self.max_size:
            self.buffer.pop(0)
        self.buffer.append(experience)

    def sample(self, batch_size: int):
        return random.sample(self.buffer, min(batch_size, len(self.buffer)))

    def clear(self):
        self.buffer.clear()
