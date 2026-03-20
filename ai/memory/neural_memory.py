import numpy as np

class NeuralMemory:

    def __init__(self):

        self.memories = []
        self.vectors = []

    def store(self, vector, data):

        self.vectors.append(vector)
        self.memories.append(data)

    def recall(self, query):

        similarities = [
            np.dot(query, v)
            for v in self.vectors
        ]

        idx = np.argmax(similarities)

        return self.memories[idx]