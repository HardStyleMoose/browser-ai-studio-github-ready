from __future__ import annotations

import numpy as np


import gymnasium as gym
from gymnasium import spaces

class UniversalEnv(gym.Env):

    def __init__(
        self,
        capture=None,
        perception=None,
        executor=None,
        perception_engine=None,
        state_builder=None,
        reward_discovery=None,
        action_discovery=None,
        action_executor=None,
    ):

        super().__init__()

        self.capture = capture
        self.perception = perception or perception_engine
        self.executor = executor or action_executor
        self.state_builder = state_builder
        self.reward_discovery = reward_discovery
        self.action_discovery = action_discovery
        self.last_state = None
        self._last_discovered_actions = []

        self.action_space = spaces.Discrete(6)

        self.observation_space = spaces.Box(
            low=-1e6,
            high=1e6,
            shape=(4,),
            dtype=np.float32,
        )

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        state = self._capture_state()
        self.last_state = state
        info = {
            "episode": 1,
            "reward": 0.0,
            "batch": False,
            "actions": self._discover_actions(),
            "action_mask": self.action_masks().tolist(),
        }
        return state, info

    def step(self, action):
        if self.executor is not None:
            self.executor.execute(action)

        state = self._capture_state()
        reward = 0.0
        if self.reward_discovery is not None:
            reward = float(self.reward_discovery.calculate_reward(state, action))

        self.last_state = state
        terminated = False
        truncated = False
        discovered_actions = self._discover_actions()
        info = {
            "episode": 1,
            "reward": reward,
            "batch": False,
            "actions": discovered_actions,
            "action_mask": self.action_masks().tolist(),
            "action_metadata": {
                "action": action,
                "valid": 0 <= int(action) < min(int(self.action_space.n), len(discovered_actions)),
            },
        }
        return state, reward, terminated, truncated, info

    def compute_reward(self, state):
        if self.reward_discovery is None:
            return 0.0
        return float(self.reward_discovery.calculate_reward(state, None))

    def _capture_state(self):
        frame = self._capture_frame()
        perception = self._analyze_frame(frame)
        if self.state_builder is not None:
            state = self.state_builder.build(perception)
        else:
            state = perception
        return np.asarray(state, dtype=np.float32)

    def _capture_frame(self):
        if callable(self.capture):
            return self.capture()
        if self.capture is not None and hasattr(self.capture, "grab"):
            return self.capture.grab()
        return np.zeros((84, 84, 3), dtype=np.uint8)

    def _analyze_frame(self, frame):
        if self.perception is None:
            return {"health": 0, "enemy_count": 0, "gold": 0, "damage": 0}
        if hasattr(self.perception, "process"):
            raw = self.perception.process(frame)
        else:
            raw = self.perception.analyze(frame)
        return self._normalize_perception(raw)

    def _normalize_perception(self, raw):
        if not isinstance(raw, dict):
            return {"health": 0, "enemy_count": 0, "gold": 0, "damage": 0}
        text = raw.get("text", "")
        ui = raw.get("ui", [])
        objects = raw.get("objects", [])
        return {
            "health": raw.get("health", 0),
            "enemy_count": raw.get("enemy_count", len(ui) if isinstance(ui, list) else 0),
            "gold": raw.get("gold", self._extract_numeric(text, "gold")),
            "damage": raw.get("damage", len(objects) if objects else 0),
        }

    def _discover_actions(self):
        if self.action_discovery is None:
            self._last_discovered_actions = []
            return []
        try:
            actions = self.action_discovery.discover_actions(self._capture_frame())
        except Exception:
            actions = []
        self._last_discovered_actions = list(actions or [])
        return self._last_discovered_actions

    def action_masks(self):
        masks = np.ones(int(self.action_space.n), dtype=bool)
        actions = list(self._last_discovered_actions or self._discover_actions() or [])
        if not actions:
            return masks
        masks[:] = False
        valid_count = min(int(self.action_space.n), len(actions))
        if valid_count <= 0:
            masks[:] = True
            return masks
        masks[:valid_count] = True
        return masks

    def _extract_numeric(self, text, label):
        if not isinstance(text, str):
            return 0
        import re

        match = re.search(rf"{label}\s*[:\-]?\s*(\d+)", text.lower())
        return int(match.group(1)) if match else 0
