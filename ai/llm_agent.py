class LLMAgent:

    def __init__(self, llm):

        self.llm = llm

    def decide(self, state):

        prompt = f"""
        Game state:
        health={state['health']}
        enemies={state['enemy_count']}
        gold={state['gold']}

        Choose action:
        attack
        heal
        retreat
        farm
        """

        response = self.llm.generate(prompt)

        return response.strip()