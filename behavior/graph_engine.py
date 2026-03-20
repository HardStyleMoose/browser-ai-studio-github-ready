"""Behavior graph execution engine."""

from __future__ import annotations
from typing import Dict, Optional

from .node_base import Node


class BehaviorGraph:
    def __init__(self, nodes: Dict[str, Node], start_node: str = "start"):
        self.nodes = nodes
        self.start_node = start_node

    def execute(self, state: dict) -> None:
        current = self.nodes.get(self.start_node)
        while current:
            current = current.run(state)
