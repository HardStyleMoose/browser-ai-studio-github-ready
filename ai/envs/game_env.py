"""Gym environment wrapper for BrowserAI Studio games."""

from __future__ import annotations

import time
from typing import Any, Dict, Tuple


import gymnasium as gym
from gymnasium import spaces


class GameEnv(gym.Env):
    @staticmethod
    def make_vector_env(env_fn, num_envs=4, **kwargs):
        from gymnasium.vector import SyncVectorEnv
        envs = [lambda: env_fn(**kwargs) for _ in range(num_envs)]
        return SyncVectorEnv(envs)

    # Example usage:
    # vector_env = GameEnv.make_vector_env(lambda: GameEnv(input_manager, state_extractor, capture_fn), num_envs=8)

    """Simple gym environment using game state extraction and input manager."""

    metadata = {"render.modes": ["human"]}

    def __init__(self, input_manager, state_extractor, capture_fn, reward_fn=None, max_steps=1000, auto_reset=True):
        from gymnasium import wrappers
        super().__init__()
        self.input_manager = input_manager
        self.state_extractor = state_extractor
        self.capture_fn = capture_fn
        self.reward_fn = reward_fn or (lambda state: 0.0)

        # Observation space: simple float vector for game state (gold, xp, level, health, damage)
        self.observation_space = spaces.Box(low=0.0, high=1e6, shape=(5,), dtype=float)

        # Action space: discrete set derived from input manager action set
        self.actions = [
            ("mouse", (500, 300)),
            ("key", "w"),
            ("key", "a"),
            ("key", "s"),
            ("key", "d"),
        ]
        self.action_space = spaces.Discrete(len(self.actions))

        self.last_state = None
        self.step_count = 0
        self.max_steps = max_steps
        self.auto_reset = auto_reset

        # Gymnasium wrappers
        self.env = wrappers.TimeLimit(self, max_episode_steps=max_steps)
        if auto_reset:
            self.env = wrappers.AutoResetWrapper(self.env)

    def reset(self, *, seed=None, options=None):
        self.step_count = 0
        frame = self.capture_fn()
        text = None
        try:
            text = self.capture_fn and self.state_extractor and self.state_extractor.extract(text)
        except Exception:
            pass
        self.last_state = self._get_state_vector(frame)
        info = {"reset_time": time.time()}
        return self.last_state, info

    def step(self, action):
        self.step_count += 1
        if action < 0 or action >= len(self.actions):
            raise ValueError("Invalid action")

        act = self.actions[action]
        if act[0] == "mouse":
            x, y = act[1]
            self.input_manager.click(x, y)
        elif act[0] == "key":
            self.input_manager.press_key(act[1])

        time.sleep(0.05)
        frame = self.capture_fn()
        next_state = self._get_state_vector(frame)
        reward = self.reward_fn(next_state)
        done = self.step_count >= self.max_steps
        truncated = False
        info = {
            "step_time": time.time(),
            "step_count": self.step_count,
            "action_mask": self.action_masks().tolist(),
        }
        self.last_state = next_state
        return next_state, reward, done, truncated, info

    def render(self, mode="human"):
        pass

    def action_masks(self):
        return [True] * int(self.action_space.n)

    def _get_state_vector(self, frame) -> Any:
        # Use state extractor if available
        if self.state_extractor:
            try:
                resources = self.state_extractor.extract(frame)
            except Exception:
                resources = None
        else:
            resources = None

        if not resources:
            resources = [0, 0, 0, 0, 0]

        return [
            float(resources[0]) if len(resources) > 0 else 0.0,
            float(resources[1]) if len(resources) > 1 else 0.0,
            float(resources[2]) if len(resources) > 2 else 0.0,
            float(resources[3]) if len(resources) > 3 else 0.0,
            float(resources[4]) if len(resources) > 4 else 0.0,
        ]
