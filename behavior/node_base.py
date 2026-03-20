"""Base node definitions for behavior graphs."""

from __future__ import annotations
from typing import Any, Optional


class Node:
    def __init__(self):
        self.next_node: Optional[Node] = None

    def run(self, state: Any) -> Optional["Node"]:
        raise NotImplementedError
