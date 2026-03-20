import re


class StateExtractor:

    def parse_resource_text(self, text):
        """Parse common resource lines into a dict of values.

        Example input:
            "Gold: 1250\nXP: 482"

        Returns:
            dict: {"gold": 1250, "xp": 482}
        """
        state = {}

        # Simple patterns for resource counters
        patterns = {
            "gold": r"gold\s*[:\-]?\s*(\d+)",
            "xp": r"xp\s*[:\-]?\s*(\d+)",
            "health": r"health\s*[:\-]?\s*(\d+)",
            "damage": r"damage\s*[:\-]?\s*(\d+)"
        }

        normalized = text.lower()
        for key, patt in patterns.items():
            m = re.search(patt, normalized)
            if m:
                try:
                    state[key] = int(m.group(1))
                except ValueError:
                    pass

        return state
