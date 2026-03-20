import cv2

from vision.yolo_detector import YOLODetector
from vision.resource_reader import ResourceReader
from ai.state_extractor import StateExtractor
from ai.progress_tracker import ProgressTracker
from ai.level_detector import LevelDetector
from ai.state_vector_builder import StateVectorBuilder
from ai.reward_engine import RewardEngine


class GameStateTracker:

    def __init__(self, yolo_model="yolov8n.pt"):
        self.detector = YOLODetector(model=yolo_model)
        self.reader = ResourceReader()
        self.extractor = StateExtractor()
        self.progress = ProgressTracker()
        self.level_detector = LevelDetector()
        self.state_builder = StateVectorBuilder()
        self.reward_engine = RewardEngine()
        self.last_state = {'gold': 0, 'xp': 0, 'level': 0, 'health': 0, 'damage': 0}
        self.last_reward = 0.0

    def update(self, frame):
        """Update game state from a new frame and compute a reward."""

        # 1) (Optional) detect UI elements using YOLO
        _ = self.detector.detect(frame)

        # 2) Read text from the screen / UI region
        text = self.reader.read_text(frame)

        # 3) Extract numeric values (gold/xp/damage/level)
        resources = self.extractor.extract(text)

        # 4) Detect level-up events
        levelup = self.level_detector.check_level_up(text)

        # 5) Build observation vector
        state_vector = self.state_builder.build(resources, damage=0, levelup=levelup)

        # 6) Compute reward from state change
        xp_gain = self.progress.compute_reward(state_vector)
        reward = self.reward_engine.compute(xp_gain, damage=0, levelup=levelup)

        # Store last state
        self.last_state = {
            'gold': state_vector[0],
            'xp': state_vector[1],
            'level': state_vector[2],
            'health': state_vector[3],
            'damage': state_vector[4]
        }
        self.last_reward = reward

        return state_vector, reward
