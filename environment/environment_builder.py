from environment.universal_env import UniversalEnv

from ai.state_builder import StateBuilder

from ai.reward_discovery import RewardDiscovery

from automation.action_discovery import ActionDiscovery

from automation.action_executor import ActionExecutor

from vision.perception_engine import PerceptionEngine

class EnvironmentBuilder:

    def __init__(self, perception_engine, ui_detector, action_executor):

        self.perception_engine = perception_engine

        self.ui_detector = ui_detector

        self.action_executor = action_executor

    def build_environment(self):
        state_builder = StateBuilder()
        reward_discovery = RewardDiscovery()
        action_discovery = ActionDiscovery(self.ui_detector)
        env = UniversalEnv(
            perception_engine=self.perception_engine,
            state_builder=state_builder,
            reward_discovery=reward_discovery,
            action_discovery=action_discovery,
            action_executor=self.action_executor
        )
        # RL wrappers and batch env support
        try:
            import gymnasium
            from gymnasium.wrappers import RecordEpisodeStatistics, TimeLimit
            env = RecordEpisodeStatistics(env)
            env = TimeLimit(env, max_episode_steps=1000)
        except ImportError:
            pass
        return env