import threading
import time

class VisionWorker(threading.Thread):

    def __init__(self, queues, perception_engine, event_bus):

        super().__init__(daemon=True)

        self.queues = queues

        self.perception_engine = perception_engine

        self.event_bus = event_bus

        self.running = True

    def run(self):

        while self.running:

            try:

                frame = self.queues.capture_queue.get(timeout=1)

                perception = self.perception_engine.process(frame)

                self.queues.vision_queue.put(perception)

                self.event_bus.emit("perception_ready", perception)

            except:

                pass

    def stop(self):

        self.running = False