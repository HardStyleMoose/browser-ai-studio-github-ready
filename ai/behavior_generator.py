class BehaviorGenerator:

    def generate(self, instructions):

        graph = {
            "nodes": [],
            "connections": []
        }

        if "attack" in instructions.lower():

            graph["nodes"].append({
                "id": "attack_node",
                "type": "action",
                "action": "attack_enemy"
            })

        if "heal" in instructions.lower():

            graph["nodes"].append({
                "id": "heal_node",
                "type": "action",
                "action": "heal"
            })

        return graph