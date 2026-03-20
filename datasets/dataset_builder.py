import os
import cv2
import json

class DatasetBuilder:

    def __init__(self, path="datasets/game_data"):

        self.path = path
        os.makedirs(path, exist_ok=True)
        self.index = 0

    def save(self, frame, labels):

        img_path = f"{self.path}/frame_{self.index}.png"
        label_path = f"{self.path}/frame_{self.index}.json"

        cv2.imwrite(img_path, frame)

        with open(label_path, "w") as f:
            json.dump(labels, f)

        self.index += 1