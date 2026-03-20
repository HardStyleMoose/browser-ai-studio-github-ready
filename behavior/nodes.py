"""Common behavior node types (actions, conditions, flow control)."""

from __future__ import annotations
import time
from typing import Any, Callable, Optional

from .node_base import Node


class ActionNode(Node):
    def __init__(self, action: Callable[..., Any]):
        super().__init__()
        self.action = action

    def run(self, state: Any) -> Optional["Node"]:
        try:
            self.action(state)
        except Exception:
            pass
        return self.next_node


class ConditionNode(Node):
    def __init__(self, condition: Callable[[Any], bool]):
        super().__init__()
        self.condition = condition
        self.true_node: Optional[Node] = None
        self.false_node: Optional[Node] = None

    def run(self, state: Any) -> Optional["Node"]:
        if self.condition(state):
            return self.true_node
        return self.false_node


class WaitNode(Node):
    def __init__(self, duration: float):
        super().__init__()
        self.duration = duration

    def run(self, state: Any) -> Optional["Node"]:
        time.sleep(self.duration)
        return self.next_node


class LoopNode(Node):
    def __init__(self, iterations: int):
        super().__init__()
        self.iterations = iterations

    def run(self, state: Any) -> Optional["Node"]:
        for _ in range(self.iterations):
            if self.next_node:
                self.next_node.run(state)
        return None
