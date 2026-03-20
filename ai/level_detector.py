class LevelDetector:

    def check_level_up(self, text):
        """Detect a level-up event based on keywords in OCR text."""
        if "level" in text.lower():
            return True
        return False
