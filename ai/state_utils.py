import re

def extract_numeric_state(text):
    """Extract numeric values from raw OCR text."""
    numbers = re.findall(r"\d+", text)
    return [int(n) for n in numbers]

def build_state_from_perception(perception):
    """Build state vector from perception dict."""
    return [
        perception.get("health", 0),
        perception.get("enemy_count", 0),
        perception.get("gold", 0),
        perception.get("damage", 0)
    ]

def build_state_vector(resources, damage, levelup):
    """Combine multiple signals into a single observation vector."""
    gold = resources[0] if len(resources) > 0 else 0
    xp = resources[1] if len(resources) > 1 else 0
    level = resources[2] if len(resources) > 2 else 0
    health = resources[3] if len(resources) > 3 else 0
    return [gold, xp, level, health, damage]
