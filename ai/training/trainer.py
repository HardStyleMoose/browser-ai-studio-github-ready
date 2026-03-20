"""Training coordinator for RL agents."""

from typing import Any


class Trainer:
    def __init__(self, agent):
        self.agent = agent

    def train_step(self, state: Any, action: Any, reward: float, next_state: Any, done: bool = False):
        if hasattr(self.agent, "update"):
            self.agent.update(state, action, reward, next_state, done)
