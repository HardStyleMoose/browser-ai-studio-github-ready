from __future__ import annotations

import json
from pathlib import Path


class GraphSerializer:
    @staticmethod
    def serialize(editor):
        nodes = []
        connections = []

        for node in editor.nodes.values():
            nodes.append(
                {
                    "id": node.node_id,
                    "type": node.node_type,
                    "title": node.title,
                    "config": node.config,
                    "position": [node.pos().x(), node.pos().y()],
                }
            )

        for connection in editor.connections:
            connections.append(
                {
                    "from": connection.start_socket.parentItem().node_id,
                    "from_socket": connection.start_socket.index,
                    "to": connection.end_socket.parentItem().node_id,
                    "to_socket": connection.end_socket.index,
                }
            )

        return {"version": 2, "nodes": nodes, "connections": connections}

    @staticmethod
    def save(editor, file_path: str):
        payload = GraphSerializer.serialize(editor)
        Path(file_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def load(file_path: str):
        return json.loads(Path(file_path).read_text(encoding="utf-8"))
