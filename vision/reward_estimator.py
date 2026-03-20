class RewardEstimator:

    def __init__(self, scale=1.0):
        self.scale = scale

    def compute_reward(self, prev_state, curr_state):
        """Compute a simple reward based on changes between states.

        Args:
            prev_state (dict): Previous state dict (e.g., {'xp': 100}).
            curr_state (dict): Current state dict.

        Returns:
            float: Reward value (positive for progress, negative for loss).
        """
        if not prev_state:
            return 0.0

        reward = 0.0

        # Reward increases in XP or gold; penalize health drops.
        if "xp" in curr_state and "xp" in prev_state:
            reward += (curr_state["xp"] - prev_state["xp"]) * 0.1

        if "gold" in curr_state and "gold" in prev_state:
            reward += (curr_state["gold"] - prev_state["gold"]) * 0.01

        if "health" in curr_state and "health" in prev_state:
            reward += (curr_state["health"] - prev_state["health"]) * 0.2

        if "damage" in curr_state and "damage" in prev_state:
            reward += (curr_state["damage"] - prev_state["damage"]) * 0.05

        return reward * self.scale
