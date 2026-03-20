class RewardEngine:

    def compute(self, xp_gain, damage, levelup):
        """Compute a combined reward from multiple signals."""
        reward = 0.0
        reward += xp_gain * 0.5
        reward += damage * 0.2
        if levelup:
            reward += 50
        return reward
