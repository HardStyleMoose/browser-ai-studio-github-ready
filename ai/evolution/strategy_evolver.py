import random

class StrategyEvolver:

    def mutate(self, strategy):

        new_strategy = strategy.copy()

        if random.random() < 0.3:
            new_strategy["attack_threshold"] += random.randint(-5,5)

        return new_strategy

    def evolve(self, population):

        population.sort(key=lambda s: s["score"], reverse=True)

        survivors = population[:3]

        new_gen = survivors.copy()

        while len(new_gen) < len(population):

            parent = random.choice(survivors)

            child = self.mutate(parent)

            new_gen.append(child)

        return new_gen