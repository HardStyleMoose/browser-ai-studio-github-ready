import threading
import time

class AgentWorker(threading.Thread):

    def __init__(self, queues, ppo_trainer, event_bus):

        super().__init__(daemon=True)

        self.queues = queues

        self.ppo_trainer = ppo_trainer

        self.event_bus = event_bus

        self.running = True

    def run(self):

        while self.running:

            try:

                perception = self.queues.vision_queue.get(timeout=1)

                if self.ppo_trainer is None:
                    action = 0
                else:
                    action = self.ppo_trainer.predict(perception)

                self.queues.agent_queue.put(action)

                self.event_bus.emit("action_decided", action)

            except:

                pass

    def stop(self):

        self.running = False