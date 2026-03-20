"""Record and replay training sessions."""

from typing import Any, List


class ReplayRecorder:
    def __init__(self):
        self.records: List[Any] = []

    def record(self, frame: Any, action: Any, reward: float) -> None:
        self.records.append({"frame": frame, "action": action, "reward": reward})

    def clear(self) -> None:
        self.records.clear()

    def playback(self) -> List[Any]:
        return list(self.records)
