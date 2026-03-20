class SelfPlayManager:

    def __init__(self, agent_class, env_class):

        self.agent_a = agent_class(env_class())
        self.agent_b = agent_class(env_class())

    def train(self, steps):

        for _ in range(steps):

            state = self.agent_a.env.reset()

            done = False

            while not done:

                action_a = self.agent_a.predict(state)
                action_b = self.agent_b.predict(state)

                state, reward, done, _ = self.agent_a.env.step(action_a)

                self.agent_a.learn(reward)
                self.agent_b.learn(-reward)