from core.pipeline_queues import PipelineQueues

from vision.capture_worker import CaptureWorker

from vision.vision_worker import VisionWorker

from ai.agent_worker import AgentWorker

from automation.action_worker import ActionWorker

class PipelineController:

    def __init__(self, capture_screen_func, perception_engine, ppo_trainer, action_executor, event_bus):

        self.capture_screen_func = capture_screen_func

        self.perception_engine = perception_engine

        self.ppo_trainer = ppo_trainer

        self.action_executor = action_executor

        self.event_bus = event_bus

        self.queues = None

        self.workers = []

        self._create_workers()

    def _create_workers(self):

        self.queues = PipelineQueues()

        self.capture_worker = CaptureWorker(self.queues, self.capture_screen_func, self.event_bus)

        self.vision_worker = VisionWorker(self.queues, self.perception_engine, self.event_bus)

        self.agent_worker = AgentWorker(self.queues, self.ppo_trainer, self.event_bus)

        self.action_worker = ActionWorker(self.queues, self.action_executor, self.event_bus)

        self.workers = [self.capture_worker, self.vision_worker, self.agent_worker, self.action_worker]

    def start(self):

        if any(worker.is_alive() for worker in self.workers):
            return

        if any(worker.ident is not None for worker in self.workers):
            self._create_workers()

        for worker in self.workers:

            worker.start()

    def stop(self):

        for worker in self.workers:

            worker.stop()

        for worker in self.workers:

            worker.join()