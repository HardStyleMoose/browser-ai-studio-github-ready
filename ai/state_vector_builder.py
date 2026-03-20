from ai.state_utils import build_state_vector

class StateVectorBuilder:
    def build(self, resources, damage, levelup):
        return build_state_vector(resources, damage, levelup)
