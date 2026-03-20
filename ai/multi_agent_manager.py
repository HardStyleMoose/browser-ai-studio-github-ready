class MultiAgentManager:

    def __init__(self, agent_class, env_class, num_agents=4):

        self.agents = []
        self.envs = []

        for _ in range(num_agents):

            env = env_class()
            agent = agent_class(env)

            self.envs.append(env)
            self.agents.append(agent)

    def train(self, steps=1000):

        for agent in self.agents:
            agent.train(steps)