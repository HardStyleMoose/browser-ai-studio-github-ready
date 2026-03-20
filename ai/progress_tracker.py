class ProgressTracker:

    def __init__(self):
        self.previous = None

    def compute_reward(self, current):
        """Compute reward based on the change between frames.

        Args:
            current (list[int]): Current state vector (e.g., [gold, xp, damage, level]).

        Returns:
            float: Reward signal (positive for improvement).
        """
        if self.previous is None:
            self.previous = current
            return 0.0

        reward = sum(current) - sum(self.previous)
        self.previous = current
        return reward
