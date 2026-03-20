import queue
import threading

class PipelineQueues:

    def __init__(self):

        self.capture_queue = queue.Queue(maxsize=10)

        self.vision_queue = queue.Queue(maxsize=10)

        self.agent_queue = queue.Queue(maxsize=10)

        self.action_queue = queue.Queue(maxsize=10)

        self.lock = threading.Lock()