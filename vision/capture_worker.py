import threading
import time
import numpy as np

class CaptureWorker(threading.Thread):

    def __init__(self, queues, capture_screen_func, event_bus):

        super().__init__(daemon=True)

        self.queues = queues

        self.capture_screen = capture_screen_func

        self.event_bus = event_bus

        self.running = True

    def run(self):

        while self.running:

            frame = self.capture_screen()

            self.queues.capture_queue.put(frame)

            self.event_bus.emit("frame_captured", frame)

            time.sleep(0.033)  # ~30 FPS

    def stop(self):

        self.running = False