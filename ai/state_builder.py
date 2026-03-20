from ai.state_utils import build_state_from_perception

class StateBuilder:
    def build(self, perception):
        return build_state_from_perception(perception)