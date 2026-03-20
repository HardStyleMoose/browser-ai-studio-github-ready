"""Simple rolling frame buffer."""

from collections import deque
from typing import Any, Deque, Optional


class FrameBuffer:
    def __init__(self, size: int = 30):
        self.frames: Deque[Any] = deque(maxlen=size)

    def push(self, frame: Any) -> None:
        self.frames.append(frame)

    def latest(self) -> Optional[Any]:
        return self.frames[-1] if self.frames else None

    def all(self) -> list:
        return list(self.frames)
