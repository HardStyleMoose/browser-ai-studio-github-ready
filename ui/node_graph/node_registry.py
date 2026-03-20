from __future__ import annotations


class NodeRegistry:
    _definitions = {
        "loop": {
            "title": "Loop",
            "category": "Flow",
            "color": "#f59e42",
            "inputs": 1,
            "outputs": 2,
            "config": {"count": 3},
        },
        "decision": {
            "title": "Decision",
            "category": "Logic",
            "color": "#eab308",
            "inputs": 1,
            "outputs": 2,
            "config": {"condition": "xp > 50"},
        },
        "action": {
            "title": "Action",
            "category": "Control",
            "color": "#2563eb",
            "inputs": 1,
            "outputs": 1,
            "config": {"action": "click", "target": [500, 300]},
        },
        "condition": {
            "title": "Condition",
            "category": "Logic",
            "color": "#059669",
            "inputs": 1,
            "outputs": 2,
            "config": {"condition": "gold >= 100"},
        },
        "wait": {
            "title": "Wait",
            "category": "Control",
            "color": "#7c3aed",
            "inputs": 1,
            "outputs": 1,
            "config": {"duration_ms": 500},
        },
        "sequence": {
            "title": "Sequence",
            "category": "Flow",
            "color": "#ea580c",
            "inputs": 1,
            "outputs": 2,
            "config": {},
        },
        "selector": {
            "title": "Selector",
            "category": "Flow",
            "color": "#dc2626",
            "inputs": 1,
            "outputs": 2,
            "config": {},
        },
    }

    @classmethod
    def all(cls):
        return cls._definitions.copy()

    @classmethod
    def get(cls, node_type: str):
        return cls._definitions[node_type]

    @classmethod
    def has(cls, node_type: str):
        return node_type in cls._definitions
