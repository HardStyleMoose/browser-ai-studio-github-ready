class DamageDetector:

    def detect_damage(self, detections):
        """Sum up detected damage values from a detection model output.

        Args:
            detections (list[dict]): List of detection dicts with keys 'class' and 'value'.

        Returns:
            int: Total damage detected.
        """
        damage = 0

        for d in detections or []:
            if d.get("class") == "damage_number":
                try:
                    damage += int(d.get("value", 0))
                except (ValueError, TypeError):
                    pass

        return damage
