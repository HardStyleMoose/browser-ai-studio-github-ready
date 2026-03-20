"""Simple performance monitoring utilities."""

import time


class PerformanceMonitor:
    def __init__(self):
        self.last = time.time()

    def tick(self) -> float:
        now = time.time()
        fps = 1.0 / (now - self.last) if now != self.last else float("inf")
        self.last = now
        return fps
