class AutonomousTrainer:

    def __init__(self, env, agent, dataset):

        self.env = env
        self.agent = agent
        self.dataset = dataset

    def run_episode(self):

        state = self.env.reset()

        done = False

        while not done:

            action = self.agent.predict(state)

            next_state, reward, done, info = self.env.step(action)

            self.agent.learn(state, action, reward, next_state)

            state = next_state