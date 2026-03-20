import threading
import time

class ActionWorker(threading.Thread):

    def __init__(self, queues, action_executor, event_bus):

        super().__init__(daemon=True)

        self.queues = queues

        self.action_executor = action_executor

        self.event_bus = event_bus

        self.running = True

    def run(self):

        while self.running:

            try:

                action = self.queues.agent_queue.get(timeout=1)

                self.action_executor.execute(action)

                self.event_bus.emit("action_executed", action)

            except:

                pass

    def stop(self):

        self.running = False