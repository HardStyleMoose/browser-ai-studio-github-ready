"""Build a BehaviorGraph from editor block definitions."""

from __future__ import annotations
from typing import Any, Callable, Dict, Optional

from .graph_engine import BehaviorGraph
from .nodes import ActionNode, ConditionNode


class BehaviorGraphBuilder:
    @staticmethod
    def build_from_dict(behavior_blocks: Dict[str, dict], input_manager=None) -> BehaviorGraph:
        """Build a BehaviorGraph from the editor's behavior_blocks dict."""

        nodes: Dict[str, Any] = {}

        def make_action_fn(block: dict) -> Callable[[Any], None]:
            def _action(state: Any):
                # Use input_manager if available
                if input_manager:
                    action_type = block.get("action")
                    target = block.get("target")
                    if action_type == "click" and isinstance(target, tuple) and len(target) == 2:
                        input_manager.click(target[0], target[1])
                    elif action_type == "key" and target:
                        input_manager.press_key(target)

            return _action

        def make_condition_fn(block: dict) -> Callable[[Any], bool]:
            condition = block.get("condition", "False")

            def _cond(state: Any) -> bool:
                try:
                    return bool(eval(condition, {}, state))
                except Exception:
                    return False

            return _cond

        # Create node instances
        for block_id, block in behavior_blocks.items():
            btype = block.get("type")
            if btype == "action":
                nodes[block_id] = ActionNode(make_action_fn(block))
            elif btype == "state":
                nodes[block_id] = ConditionNode(make_condition_fn(block))
            else:
                # Fallback to no-op action
                nodes[block_id] = ActionNode(lambda state: None)

        # Attach connections
        for block_id, block in behavior_blocks.items():
            node = nodes.get(block_id)
            connections = block.get("connections", []) or []
            if isinstance(node, ConditionNode):
                if len(connections) >= 1:
                    node.true_node = nodes.get(connections[0])
                if len(connections) >= 2:
                    node.false_node = nodes.get(connections[1])
            else:
                # For actions and others, chain sequentially
                if connections:
                    node.next_node = nodes.get(connections[0])

        # Determine start node(s) - choose those with no incoming connections
        incoming = set()
        for block in behavior_blocks.values():
            for c in block.get("connections", []) or []:
                incoming.add(c)

        roots = [bid for bid in behavior_blocks.keys() if bid not in incoming]
        start = roots[0] if roots else (next(iter(behavior_blocks.keys()), None))

        return BehaviorGraph(nodes, start_node=start)
