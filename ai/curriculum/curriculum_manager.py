class CurriculumManager:

    def __init__(self):

        self.stage = 0

        self.stages = [
            {"reward_scale": 1, "difficulty": 1},
            {"reward_scale": 2, "difficulty": 2},
            {"reward_scale": 3, "difficulty": 3}
        ]

    def get_stage(self):
        return self.stages[self.stage]

    def advance(self):
        if self.stage < len(self.stages) - 1:
            self.stage += 1